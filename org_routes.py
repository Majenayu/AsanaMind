"""
AsanMinds · Multi-tenant organization layer
============================================

Adds an "organizations" tier on top of the user model so the app can be sold
to many colleges/companies. Each organization has:

  • a primary contact email (the org-admin) who runs their own sub-admin panel
  • a domain whitelist (only @vvce.ac.in students can sign in for VVCE)
  • licensed seats (studentCap)
  • paid status (binary, no refunds)
  • configurable batches / branches / sections so org-admins can model
    their academic structure however the college organises students

Roles
-----
  super_admin   — you (pgayushrai@gmail.com). Adds organizations, has the
                  hidden live-coach view, can see across all orgs.
  org_admin     — an org's primary contact. Sub-admin powers within their
                  organization only. NO live coach view, NO ability to
                  manage other organizations.
  student       — end user. Practises, earns certificates.

This file exposes a function `register_org_routes(app, deps)` that wires
everything into the existing Flask app object. Call it once from app.py
right before app.run.
"""
from __future__ import annotations

import csv
import io
import json
import secrets
from datetime import datetime, timedelta
from functools import wraps

from flask import jsonify, request, session, redirect, url_for, render_template_string

# Default seed values for a new organization.
DEFAULT_BATCHES = ['2022', '2023', '2024', '2025']
DEFAULT_BRANCHES = []  # let the org fill these in themselves
DEFAULT_SECTIONS = ['A', 'B', 'C', 'D']

# Special "test" organization for legacy users who existed before this
# multi-tenant layer was introduced. Hidden from the regular org list.
TEST_ORG_EMAIL = 'test@asanminds.local'


# ─────────────────────────────────────────────────────────────
# Helpers — pure functions, no dependencies on Flask state
# ─────────────────────────────────────────────────────────────

def current_semester_for(batch, now=None):
    """Compute current academic semester from a 4-digit batch year.

    A 2023-batch student in:
        Aug 2023 → sem 1
        Feb 2024 → sem 2
        Aug 2024 → sem 3
        ...
        Aug 2027 → sem 9 → clamped to 8

    July is the academic year boundary (typical Indian engineering colleges).
    """
    try:
        y = int(batch)
    except Exception:
        return 0
    today = now or datetime.utcnow()
    in_second_half = today.month >= 7
    year_diff = today.year - y
    sem = year_diff * 2 + (1 if in_second_half else 2)
    if sem < 1:
        return 0
    if sem > 8:
        return 8
    return sem


def domain_of(email):
    """Returns the lowercase domain part of an email, or '' if invalid."""
    em = (email or '').strip().lower()
    if '@' not in em:
        return ''
    return em.split('@', 1)[1]


def _audit_safe(audit_col, action, target='', meta=None, actor=None):
    """Append to admin_audit if available; never crash on logging."""
    if audit_col is None:
        return
    try:
        audit_col.insert_one({
            'admin_email': actor or session.get('admin_email') or session.get('user_email'),
            'action': action,
            'target_email': target,
            'meta': meta or {},
            'ts': datetime.utcnow().isoformat(),
        })
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────
# Public registration function — call from app.py
# ─────────────────────────────────────────────────────────────

def register_org_routes(app, deps):
    """Wire all multi-tenant routes onto the given Flask app.

    deps is a dict of references the org module needs from app.py:
      - organizations_col
      - invitations_col
      - admin_audit_col
      - g_users (Mongo collection — Google-signed-in users live here)
      - users   (Mongo collection — legacy email-flow users)
      - feedback_col
      - certificates_col, g_certificates_col
      - course_progress_col, g_course_progress_col
      - push_subs_col, g_push_subs_col
      - webpush_send (callable)   : (email, title, body) -> bool
      - sendgrid_send (callable)  : (to, subject, html_body) -> bool
      - admin_emails  (set)       : super-admin email allowlist
    """
    organizations_col = deps['organizations_col']
    invitations_col = deps['invitations_col']
    admin_audit_col = deps.get('admin_audit_col')
    g_users = deps['g_users']
    users = deps['users']
    feedback_col = deps.get('feedback_col')
    g_cert_col = deps.get('g_certificates_col')
    cert_col = deps.get('certificates_col')
    g_cp_col = deps.get('g_course_progress_col')
    cp_col = deps.get('course_progress_col')
    g_push_col = deps.get('g_push_subs_col')
    push_col = deps.get('push_subs_col')
    sendgrid_send = deps.get('sendgrid_send')
    webpush_send = deps.get('webpush_send')
    admin_emails = deps.get('admin_emails', set())

    # Ensure the test organization exists (one-time migration on first deploy).
    if organizations_col is not None:
        try:
            existing = organizations_col.find_one({'email': TEST_ORG_EMAIL})
            if not existing:
                organizations_col.insert_one({
                    'email': TEST_ORG_EMAIL,
                    'name': 'AsanMinds Test Org',
                    'domain': '*',
                    'studentCap': 9999,
                    'studentsEnrolled': 0,
                    'paid': True,
                    'paidUntil': None,
                    'batches': ['test'],
                    'branches': [{'code': 'TEST', 'name': 'Test users'}],
                    'sections': ['T'],
                    'system': True,
                    'createdAt': datetime.utcnow(),
                    'createdByAdmin': 'system',
                })
                print(f"✓ Created system organization {TEST_ORG_EMAIL}")
        except Exception as e:
            print(f'⚠ test-org init: {e}')

        # Backfill: every existing user without role/org gets attached to test org.
        for col, default_provider in ((g_users, 'google'), (users, 'email')):
            if col is None:
                continue
            try:
                col.update_many(
                    {'role': {'$exists': False}},
                    {'$set': {
                        'role': 'student',
                        'organizationEmail': TEST_ORG_EMAIL,
                        'academic': {'batch': 'test', 'branch': 'TEST', 'section': 'T'},
                        'paidStatus': 'test',
                        'auth_provider': default_provider,
                    }}
                )
            except Exception as e:
                print(f'⚠ legacy user backfill ({default_provider}): {e}')

    # ─────────────────────────────────────────────────────────
    # Auth helpers — decorators
    # ─────────────────────────────────────────────────────────

    def _is_super_admin():
        """Wraps the existing super-admin gate so we can use it independently."""
        return bool(
            session.get('admin_unlocked') and
            (session.get('admin_email') or '').lower() in admin_emails
        )

    def _is_org_admin():
        """Returns the org email if the current session belongs to an org-admin, else None.

        An org-admin is identified by:
          - logged_in via Google
          - role == 'org_admin' (set when they accept their invitation)
          - their email matches the organization's primary email
        """
        if not session.get('logged_in'):
            return None
        if session.get('role') != 'org_admin':
            return None
        return session.get('organizationEmail')

    def super_admin_required(f):
        @wraps(f)
        def w(*a, **k):
            if not _is_super_admin():
                return jsonify({'error': 'Super-admin only'}), 401
            return f(*a, **k)
        return w

    def org_admin_required(f):
        @wraps(f)
        def w(*a, **k):
            org_email = _is_org_admin()
            if not org_email:
                return jsonify({'error': 'Organization admin required'}), 401
            request._org_email = org_email
            return f(*a, **k)
        return w

    # ─────────────────────────────────────────────────────────
    # Org CRUD — super-admin only
    # ─────────────────────────────────────────────────────────

    @app.route('/api/admin/organizations', methods=['GET'])
    @super_admin_required
    def list_organizations():
        if organizations_col is None:
            return jsonify({'organizations': []})
        show_system = request.args.get('system') == '1'
        q = {} if show_system else {'system': {'$ne': True}}
        rows = []
        for o in organizations_col.find(q).sort('createdAt', -1):
            o.pop('_id', None)
            # Live student count (cheap if you cache, but live for now).
            email = o.get('email')
            cnt = 0
            if g_users is not None:
                cnt += g_users.count_documents({'organizationEmail': email})
            if users is not None:
                cnt += users.count_documents({'organizationEmail': email})
            o['studentsEnrolled'] = cnt
            rows.append(o)
        return jsonify({'organizations': rows})

    @app.route('/api/admin/organization', methods=['POST'])
    @super_admin_required
    def create_organization():
        if organizations_col is None:
            return jsonify({'success': False, 'error': 'DB offline'}), 503
        data = request.get_json(silent=True) or {}
        email = (data.get('email') or '').strip().lower()
        name = (data.get('name') or '').strip()
        domain = (data.get('domain') or '').strip().lower().lstrip('@')
        try:
            cap = int(data.get('studentCap') or 0)
        except Exception:
            cap = 0
        if not email or not name or not domain or cap <= 0:
            return jsonify({'success': False, 'error': 'email, name, domain and studentCap are required'}), 400
        if organizations_col.find_one({'email': email}):
            return jsonify({'success': False, 'error': 'An organization with that email already exists.'}), 409

        organizations_col.insert_one({
            'email': email,
            'name': name,
            'domain': domain,
            'studentCap': cap,
            'studentsEnrolled': 0,
            'paid': bool(data.get('paid', True)),
            'paidUntil': data.get('paidUntil'),
            'batches': list(DEFAULT_BATCHES),
            'branches': list(DEFAULT_BRANCHES),
            'sections': list(DEFAULT_SECTIONS),
            'system': False,
            'createdAt': datetime.utcnow(),
            'createdByAdmin': session.get('admin_email'),
        })
        _audit_safe(admin_audit_col, 'org_create', email, {'name': name, 'domain': domain, 'cap': cap})

        # Auto-create a magic-link invitation for the org-admin and email it.
        # The org's contact email IS the first sub-admin's account by design,
        # so this is what makes "registering an org" actually do something
        # visible to the user — they get a Google sign-in link in their inbox.
        invite_link = None
        email_sent = False
        if invitations_col is not None:
            try:
                # Drop any prior pending invite for this email+org pair to avoid
                # ambiguity if the super-admin recreates an org.
                invitations_col.delete_many({
                    'email': email,
                    'organizationEmail': email,
                    'role': 'org_admin',
                    'status': 'pending',
                })
                token = secrets.token_hex(20)
                invitations_col.insert_one({
                    'email': email,
                    'token': token,
                    'inviterEmail': session.get('admin_email'),
                    'organizationEmail': email,
                    'role': 'org_admin',
                    'status': 'pending',
                    'prefilled': {'name': name},
                    'createdAt': datetime.utcnow(),
                })
                invite_link = request.url_root.rstrip('/') + '/invite/' + token
                email_sent = bool(_send_invite_email(email, 'org_admin', invite_link, name, prefilled_name=name))
                _audit_safe(admin_audit_col, 'invite_org_admin', email, {'org': email, 'sent': email_sent, 'auto': True})
            except Exception as exc:
                # Don't fail the whole org creation if mail dispatch fails;
                # super-admin can resend from the Organizations tab.
                try:
                    app.logger.warning('Auto-invite on org create failed: %r', exc)
                except Exception:
                    pass

        return jsonify({
            'success': True,
            'inviteLink': invite_link,
            'emailSent': email_sent,
            'message': (
                'Organization created and an admin invitation was emailed.'
                if email_sent else
                'Organization created. Email could not be sent automatically — share the invitation link manually.'
            ),
        })

    @app.route('/api/admin/organization/<path:email>', methods=['PUT'])
    @super_admin_required
    def edit_organization(email):
        if organizations_col is None:
            return jsonify({'success': False, 'error': 'DB offline'}), 503
        email = email.lower()
        data = request.get_json(silent=True) or {}
        update = {}
        for k in ('name', 'domain', 'paid', 'paidUntil'):
            if k in data:
                update[k] = data[k]
        if 'studentCap' in data:
            try:
                update['studentCap'] = int(data['studentCap'])
            except Exception:
                pass
        if not update:
            return jsonify({'success': False, 'error': 'Nothing to update.'}), 400
        if 'domain' in update:
            update['domain'] = (update['domain'] or '').strip().lower().lstrip('@')
        res = organizations_col.update_one({'email': email}, {'$set': update})
        if not res.matched_count:
            return jsonify({'success': False, 'error': 'Not found.'}), 404
        _audit_safe(admin_audit_col, 'org_edit', email, update)
        return jsonify({'success': True})

    @app.route('/api/admin/organization/<path:email>', methods=['DELETE'])
    @super_admin_required
    def delete_organization(email):
        if organizations_col is None:
            return jsonify({'success': False, 'error': 'DB offline'}), 503
        email = email.lower()
        if email == TEST_ORG_EMAIL:
            return jsonify({'success': False, 'error': 'Cannot delete the system test organization.'}), 400
        # Detach all students rather than deleting them.
        for col in (g_users, users):
            if col is not None:
                col.update_many({'organizationEmail': email}, {'$set': {'organizationEmail': None}})
        organizations_col.delete_one({'email': email})
        if invitations_col is not None:
            invitations_col.delete_many({'organizationEmail': email})
        _audit_safe(admin_audit_col, 'org_delete', email)
        return jsonify({'success': True})

    # ─────────────────────────────────────────────────────────
    # Org-admin self APIs
    # ─────────────────────────────────────────────────────────

    @app.route('/api/org/me', methods=['GET'])
    @org_admin_required
    def org_me():
        org_email = request._org_email
        org = organizations_col.find_one({'email': org_email}) if organizations_col is not None else None
        if not org:
            return jsonify({'error': 'Organization not found'}), 404
        org.pop('_id', None)
        return jsonify({
            'admin': {
                'email': session.get('user_email'),
                'name': session.get('user_name'),
                'picture': session.get('picture'),
            },
            'organization': org,
        })

    @app.route('/api/org/config', methods=['PUT'])
    @org_admin_required
    def org_edit_config():
        """Org-admin edits batches/branches/sections."""
        org_email = request._org_email
        data = request.get_json(silent=True) or {}
        update = {}
        if 'batches' in data and isinstance(data['batches'], list):
            update['batches'] = [str(b).strip() for b in data['batches'] if str(b).strip()]
        if 'sections' in data and isinstance(data['sections'], list):
            update['sections'] = [str(s).strip().upper() for s in data['sections'] if str(s).strip()]
        if 'branches' in data and isinstance(data['branches'], list):
            cleaned = []
            for b in data['branches']:
                if isinstance(b, dict) and b.get('code'):
                    cleaned.append({
                        'code': str(b['code']).strip().upper(),
                        'name': str(b.get('name') or b['code']).strip(),
                    })
                elif isinstance(b, str) and b.strip():
                    cleaned.append({'code': b.strip().upper(), 'name': b.strip()})
            update['branches'] = cleaned
        if not update:
            return jsonify({'success': False, 'error': 'Nothing to update.'}), 400
        organizations_col.update_one({'email': org_email}, {'$set': update})
        _audit_safe(admin_audit_col, 'org_config_edit', org_email, list(update.keys()))
        return jsonify({'success': True})

    # ─────────────────────────────────────────────────────────
    # Org-admin students APIs (scoped to own org only)
    # ─────────────────────────────────────────────────────────

    def _filter_for_org(org_email, q_args):
        """Build a Mongo query that's always scoped to one org, plus optional batch/branch/section filters."""
        f = {'organizationEmail': org_email}
        if q_args.get('batch'):
            f['academic.batch'] = q_args['batch']
        if q_args.get('branch'):
            f['academic.branch'] = q_args['branch']
        if q_args.get('section'):
            f['academic.section'] = q_args['section']
        return f

    @app.route('/api/org/students', methods=['GET'])
    @org_admin_required
    def org_students():
        org_email = request._org_email
        f = _filter_for_org(org_email, request.args)
        rows = []
        for col in (g_users, users):
            if col is None:
                continue
            for u in col.find(f):
                u.pop('_id', None)
                rows.append({
                    'email': u.get('email'),
                    'name': u.get('name'),
                    'picture': u.get('picture'),
                    'role': u.get('role'),
                    'auth_provider': u.get('auth_provider'),
                    'created_at': u.get('created_at').isoformat() if hasattr(u.get('created_at'), 'isoformat') else u.get('created_at'),
                    'academic': u.get('academic') or {},
                    'paidStatus': u.get('paidStatus'),
                    'last_active': max(u.get('activity_log') or [], default=None),
                })
        rows.sort(key=lambda r: ((r.get('academic') or {}).get('batch') or '', (r.get('academic') or {}).get('branch') or '', (r.get('academic') or {}).get('section') or '', r.get('email') or ''))
        return jsonify({'students': rows})

    @app.route('/api/org/student/<path:email>', methods=['PUT'])
    @org_admin_required
    def org_edit_student(email):
        org_email = request._org_email
        target = email.lower().strip()
        data = request.get_json(silent=True) or {}
        update = {}
        if 'name' in data:
            update['name'] = (data.get('name') or '').strip()[:120]
        if 'academic' in data and isinstance(data['academic'], dict):
            a = data['academic']
            cleaned = {}
            for k in ('batch', 'branch', 'section', 'usn', 'rollNumber', 'currentSemester'):
                if k in a:
                    cleaned[k] = (str(a[k]).strip() if a[k] is not None else None)
            update['academic'] = cleaned
        if not update:
            return jsonify({'success': False, 'error': 'Nothing to update.'}), 400
        # Critical — only target users in the same org.
        for col in (g_users, users):
            if col is None:
                continue
            col.update_one({'email': target, 'organizationEmail': org_email}, {'$set': update})
        _audit_safe(admin_audit_col, 'org_student_edit', target, update, actor=session.get('user_email'))
        return jsonify({'success': True})

    @app.route('/api/org/student/<path:email>', methods=['DELETE'])
    @org_admin_required
    def org_delete_student(email):
        org_email = request._org_email
        target = email.lower().strip()
        # Hard-delete only within this org's tenancy. Cross-org email collisions are
        # impossible because email is unique per user document and each user
        # belongs to one org.
        for col in (g_users, users):
            if col is None:
                continue
            col.delete_one({'email': target, 'organizationEmail': org_email})
        _audit_safe(admin_audit_col, 'org_student_delete', target, actor=session.get('user_email'))
        return jsonify({'success': True})

    # ─────────────────────────────────────────────────────────
    # Bulk operations on a list of student emails
    # ─────────────────────────────────────────────────────────

    @app.route('/api/org/students/bulk', methods=['POST'])
    @org_admin_required
    def org_students_bulk():
        """Bulk action on a set of student emails within this org.

        Body: {
          action: 'delete' | 'reset_progress' | 'move_section' | 'move_branch' | 'move_batch' | 'mark_paid' | 'mark_unpaid',
          emails: ['student1@..', ...],
          target: 'B'   // for move_*, the new value
        }
        Every operation is scoped to organizationEmail = current org's email
        so an org-admin can never touch a different org's students.
        """
        org_email = request._org_email
        data = request.get_json(silent=True) or {}
        action = (data.get('action') or '').strip()
        raw_emails = data.get('emails') or []
        target = data.get('target')
        if not action or not isinstance(raw_emails, list) or not raw_emails:
            return jsonify({'success': False, 'error': 'action and emails are required.'}), 400
        # Cap batch size to keep a single request fast.
        emails = [str(e).strip().lower() for e in raw_emails if e][:2000]

        scope = {'email': {'$in': emails}, 'organizationEmail': org_email}
        affected = 0
        try:
            if action == 'delete':
                # Hard-delete student docs. Doesn't touch certificates (verifiable
                # records of completion shouldn't disappear — admin can use the
                # super-admin /delete for that).
                for col in (g_users, users):
                    if col is None:
                        continue
                    res = col.delete_many(scope)
                    affected += res.deleted_count

            elif action == 'reset_progress':
                update = {'$set': {'completed_asanas': {}, 'session_history': []}}
                # Also wipe their course-progress docs in both DBs.
                for label in ('g_course_progress_col', 'course_progress_col'):
                    pass  # handled below via app-level helpers if available
                for col in (g_users, users):
                    if col is None:
                        continue
                    res = col.update_many(scope, update)
                    affected += res.modified_count

            elif action == 'move_section' and target:
                t = str(target).strip().upper()
                update = {'$set': {'academic.section': t}}
                for col in (g_users, users):
                    if col is None:
                        continue
                    res = col.update_many(scope, update)
                    affected += res.modified_count

            elif action == 'move_branch' and target:
                t = str(target).strip().upper()
                update = {'$set': {'academic.branch': t}}
                for col in (g_users, users):
                    if col is None:
                        continue
                    res = col.update_many(scope, update)
                    affected += res.modified_count

            elif action == 'move_batch' and target:
                t = str(target).strip()
                # When moving batch, also recompute current semester so the
                # course system shows the right open sem.
                new_sem = current_semester_for(t)
                update = {'$set': {
                    'academic.batch': t,
                    'academic.currentSemester': new_sem,
                }}
                for col in (g_users, users):
                    if col is None:
                        continue
                    res = col.update_many(scope, update)
                    affected += res.modified_count

            elif action in ('mark_paid', 'mark_unpaid'):
                update = {'$set': {'paidStatus': 'paid' if action == 'mark_paid' else 'unpaid'}}
                for col in (g_users, users):
                    if col is None:
                        continue
                    res = col.update_many(scope, update)
                    affected += res.modified_count
            else:
                return jsonify({'success': False, 'error': f'Unknown action "{action}" or missing target.'}), 400
        except Exception as e:
            print(f'bulk op error: {e}')
            return jsonify({'success': False, 'error': str(e)[:200]}), 500

        _audit_safe(admin_audit_col, f'org_bulk_{action}', org_email,
                    {'count': len(emails), 'affected': affected, 'target': target},
                    actor=session.get('user_email'))
        return jsonify({'success': True, 'affected': affected, 'requested': len(emails)})

    # ─────────────────────────────────────────────────────────
    # Invitations
    # ─────────────────────────────────────────────────────────

    def _send_invite_email(to, role, invite_link, org_name, prefilled_name=''):
        """Sends the invitation magic link via SendGrid (Path A).

        Branded HTML email — cream paper aesthetic matching the AsanMinds
        product. Two voice tones depending on role: warm/student vs.
        professional/admin.
        """
        if not sendgrid_send:
            return False

        is_admin = role == 'org_admin'
        first_name = (prefilled_name or to.split('@')[0]).split()[0] if prefilled_name or to else 'there'
        first_name = first_name[:30]

        if is_admin:
            subject = f"You're invited to run AsanMinds for {org_name}"
            kicker_text = 'Organization access'
            heading = f'Welcome aboard, {first_name}.'
            sub = (
                f'<b>{org_name}</b> has been onboarded to AsanMinds. As the '
                f'designated organization admin, you\'ll manage student '
                f'enrollment, track progress across cohorts, and see live '
                f'wellness analytics for your campus.'
            )
            cta_label = 'Access your admin panel'
            footer_pitch = (
                'After signing in, head to the Bulk import tab to onboard '
                'your first batch in minutes.'
            )
        else:
            subject = f'Welcome to AsanMinds — your yoga journey starts at {org_name}'
            kicker_text = 'You\'re invited'
            heading = f'Hi {first_name}, your mat is ready.'
            sub = (
                f'{org_name} has enrolled you in <b>AsanMinds</b> — an AI '
                f'yoga programme that meets you where you are. Earn your '
                f'first certificate as you move from foundation poses to '
                f'master-level standing balances over six semesters.'
            )
            cta_label = 'Begin your practice'
            footer_pitch = (
                'AsanMinds works in your browser — no download. Use '
                'Chrome or Safari on a phone or laptop with a camera.'
            )

        html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
</head>
<body style="margin:0; padding:0; background:#F5F2EB; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; color:#14120E;">
  <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="background:#F5F2EB;">
    <tr>
      <td align="center" style="padding: 32px 16px 8px;">
        <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="560" style="max-width: 560px; width: 100%;">
          <tr>
            <td style="padding: 0 8px 24px;">
              <table cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td style="background:#0F3D2E; color:#F5F2EB; width:36px; height:36px; text-align:center; vertical-align:middle; font-family: Georgia, 'Times New Roman', serif; font-size:18px; font-weight:300; border-radius:8px;">s</td>
                  <td style="padding-left:12px; font-family: Georgia, 'Times New Roman', serif; font-size:21px; font-weight:500; color:#14120E; letter-spacing:-0.01em;">sunday <span style="color:#A8A294; font-size:13px; font-weight:400;">· asanminds</span></td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td style="background:#FFFFFF; border:1px solid #D4CCB8; border-radius:24px; padding:36px 32px; box-shadow: 0 8px 24px rgba(20,18,14,0.04);">
              <p style="margin:0; color:#C2552F; font-size:11px; font-weight:600; letter-spacing:0.22em; text-transform:uppercase;">{kicker_text}</p>
              <h1 style="margin:8px 0 14px; font-family: Georgia, 'Times New Roman', serif; font-size:34px; font-weight:300; line-height:1.15; color:#14120E; letter-spacing:-0.02em;">{heading}</h1>
              <p style="margin:0 0 24px; color:#4A453B; font-size:15px; line-height:1.65;">{sub}</p>
              <table role="presentation" cellspacing="0" cellpadding="0" border="0">
                <tr>
                  <td style="border-radius:9999px; background:#0F3D2E;">
                    <a href="{invite_link}" style="display:inline-block; padding:15px 32px; color:#F5F2EB; text-decoration:none; font-size:15px; font-weight:600; letter-spacing:0.02em; border-radius:9999px;">{cta_label} →</a>
                  </td>
                </tr>
              </table>
              <p style="margin:24px 0 0; color:#7A7364; font-size:12px; line-height:1.6;">
                {footer_pitch}
              </p>
              <hr style="border:0; border-top:1px solid #E0D9C8; margin:28px 0 18px;">
              <p style="margin:0; color:#A8A294; font-size:11px; line-height:1.5;">
                If the button doesn't work, copy and paste this link into your browser:<br>
                <span style="color:#0F3D2E; word-break:break-all;">{invite_link}</span>
              </p>
              <p style="margin:18px 0 0; color:#A8A294; font-size:11px;">
                This invitation is single-use and expires after acceptance. Sign in with the same Google account this email was sent to.
              </p>
            </td>
          </tr>
          <tr>
            <td style="padding:24px 8px; color:#A8A294; font-size:11px; text-align:center;">
              Sent by <b style="color:#7A7364;">Sunday · AsanMinds</b> on behalf of {org_name} ·
              <a href="mailto:pgayushrai@gmail.com" style="color:#7A7364; text-decoration:underline;">Contact</a>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""
        return sendgrid_send(to, subject, html)


    def _send_welcome_email(to, name, org_name):
        """Sent to a student AFTER they successfully accept their invitation
        and complete Google sign-in. Confirms enrolment and points them at
        the first lesson.
        """
        if not sendgrid_send:
            return False
        first = (name or to.split('@')[0]).split()[0][:30]
        subject = f"You're in — welcome to AsanMinds, {first}."
        html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
</head>
<body style="margin:0; padding:0; background:#F5F2EB; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; color:#14120E;">
  <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="background:#F5F2EB;">
    <tr>
      <td align="center" style="padding: 32px 16px 8px;">
        <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="560" style="max-width: 560px; width: 100%;">
          <tr>
            <td style="background:#0F3D2E; color:#F5F2EB; border-radius:24px 24px 0 0; padding:40px 32px 32px;">
              <p style="margin:0; color:#E0A23F; font-size:11px; font-weight:600; letter-spacing:0.22em; text-transform:uppercase;">Welcome aboard</p>
              <h1 style="margin:10px 0 0; font-family: Georgia, 'Times New Roman', serif; font-size:36px; font-weight:300; line-height:1.1; color:#F5F2EB; letter-spacing:-0.02em;">Hi {first}, your mat is set.</h1>
              <p style="margin:14px 0 0; color:#C7DBCE; font-size:15px; line-height:1.6;">You're enrolled in {org_name}'s AsanMinds programme. Six semesters, twenty asanas, one calmer you.</p>
            </td>
          </tr>
          <tr>
            <td style="background:#FFFFFF; border:1px solid #D4CCB8; border-top:0; border-radius:0 0 24px 24px; padding:32px;">
              <p style="margin:0 0 14px; font-family: Georgia, serif; font-size:20px; font-weight:400; color:#14120E;">Three things to try first</p>
              <table cellspacing="0" cellpadding="0" border="0" width="100%">
                <tr>
                  <td style="padding:12px 0; border-bottom:1px solid #E0D9C8;">
                    <p style="margin:0; color:#0F3D2E; font-size:13px; font-weight:600;">1. Browse the library</p>
                    <p style="margin:4px 0 0; color:#7A7364; font-size:13px; line-height:1.55;">All 20 asanas with detailed notes — Sanskrit name, alignment cues, common mistakes.</p>
                  </td>
                </tr>
                <tr>
                  <td style="padding:12px 0; border-bottom:1px solid #E0D9C8;">
                    <p style="margin:0; color:#0F3D2E; font-size:13px; font-weight:600;">2. Try the AR coach</p>
                    <p style="margin:4px 0 0; color:#7A7364; font-size:13px; line-height:1.55;">Allow camera access, pick Tadasana, and watch your alignment score in real time.</p>
                  </td>
                </tr>
                <tr>
                  <td style="padding:12px 0;">
                    <p style="margin:0; color:#0F3D2E; font-size:13px; font-weight:600;">3. Start Semester 3</p>
                    <p style="margin:4px 0 0; color:#7A7364; font-size:13px; line-height:1.55;">Foundations. Pass each pose's AR test plus quiz to earn your first certificate.</p>
                  </td>
                </tr>
              </table>
              <table role="presentation" cellspacing="0" cellpadding="0" border="0" style="margin-top:24px;">
                <tr>
                  <td style="border-radius:9999px; background:#C2552F;">
                    <a href="https://asanamindvvce.onrender.com/home" style="display:inline-block; padding:14px 28px; color:#F5F2EB; text-decoration:none; font-size:14px; font-weight:600; border-radius:9999px;">Open AsanMinds</a>
                  </td>
                </tr>
              </table>
              <p style="margin:24px 0 0; color:#A8A294; font-size:11px;">
                Need help? Reach your organization admin or write to <a href="mailto:pgayushrai@gmail.com" style="color:#7A7364;">pgayushrai@gmail.com</a>.
              </p>
            </td>
          </tr>
          <tr>
            <td style="padding:20px 8px; color:#A8A294; font-size:11px; text-align:center;">
              <b style="color:#7A7364;">Sunday · AsanMinds</b> · enrolled via {org_name}
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""
        return sendgrid_send(to, subject, html)

    @app.route('/api/admin/invite-org-admin', methods=['POST'])
    @super_admin_required
    def invite_org_admin():
        """Super-admin invites a new org-admin (sub-admin)."""
        if invitations_col is None or organizations_col is None:
            return jsonify({'success': False, 'error': 'DB offline'}), 503
        data = request.get_json(silent=True) or {}
        email = (data.get('email') or '').strip().lower()
        org_email = (data.get('organizationEmail') or '').strip().lower()
        if not email or not org_email:
            return jsonify({'success': False, 'error': 'email and organizationEmail are required.'}), 400
        org = organizations_col.find_one({'email': org_email})
        if not org:
            return jsonify({'success': False, 'error': 'Organization not found.'}), 404

        token = secrets.token_hex(20)
        invitations_col.insert_one({
            'email': email,
            'token': token,
            'inviterEmail': session.get('admin_email'),
            'organizationEmail': org_email,
            'role': 'org_admin',
            'status': 'pending',
            'prefilled': {},
            'createdAt': datetime.utcnow(),
        })
        link = request.url_root.rstrip('/') + '/invite/' + token
        sent = _send_invite_email(email, 'org_admin', link, org.get('name', 'AsanMinds'))
        _audit_safe(admin_audit_col, 'invite_org_admin', email, {'org': org_email, 'sent': sent})
        return jsonify({'success': True, 'inviteLink': link, 'emailSent': bool(sent)})

    @app.route('/api/org/invite-student', methods=['POST'])
    @org_admin_required
    def invite_student():
        """Org-admin invites a single student. Pre-fills academic info."""
        if invitations_col is None:
            return jsonify({'success': False, 'error': 'DB offline'}), 503
        org_email = request._org_email
        org = organizations_col.find_one({'email': org_email})
        data = request.get_json(silent=True) or {}
        email = (data.get('email') or '').strip().lower()
        if not email:
            return jsonify({'success': False, 'error': 'email required.'}), 400

        # Domain check.
        if org and org.get('domain') and org['domain'] != '*':
            if not email.endswith('@' + org['domain']):
                return jsonify({'success': False, 'error': f"Email must end in @{org['domain']}."}), 400

        # Cap check.
        cap = int(org.get('studentCap') or 0) if org else 0
        if cap:
            current = sum(c.count_documents({'organizationEmail': org_email}) for c in (g_users, users) if c is not None)
            pending = invitations_col.count_documents({'organizationEmail': org_email, 'status': 'pending', 'role': 'student'})
            if current + pending >= cap:
                return jsonify({'success': False, 'error': f'Seat cap ({cap}) reached for this org.'}), 409

        prefilled = {}
        for k in ('batch', 'branch', 'section', 'usn', 'rollNumber', 'name'):
            if data.get(k):
                prefilled[k] = str(data[k]).strip()

        token = secrets.token_hex(20)
        invitations_col.insert_one({
            'email': email,
            'token': token,
            'inviterEmail': session.get('user_email'),
            'organizationEmail': org_email,
            'role': 'student',
            'status': 'pending',
            'prefilled': prefilled,
            'createdAt': datetime.utcnow(),
        })
        link = request.url_root.rstrip('/') + '/invite/' + token
        sent = _send_invite_email(email, 'student', link, org.get('name', 'AsanMinds') if org else 'AsanMinds')
        return jsonify({'success': True, 'inviteLink': link, 'emailSent': bool(sent)})

    @app.route('/api/org/invitations', methods=['GET'])
    @org_admin_required
    def list_invitations():
        org_email = request._org_email
        rows = []
        if invitations_col is not None:
            for inv in invitations_col.find({'organizationEmail': org_email}).sort('createdAt', -1).limit(500):
                inv.pop('_id', None)
                inv.pop('token', None)  # don't leak unused tokens to UI
                if hasattr(inv.get('createdAt'), 'isoformat'):
                    inv['createdAt'] = inv['createdAt'].isoformat()
                rows.append(inv)
        return jsonify({'invitations': rows})

    # ─────────────────────────────────────────────────────────
    # Semester recompute — for org-admin manual trigger or super-admin cron
    # ─────────────────────────────────────────────────────────

    def _recompute_semesters_for_org(org_email):
        """Walk every student in the org and recompute academic.currentSemester
        from their batch year + today's date. Returns count updated.
        """
        if g_users is None and users is None:
            return 0
        updated = 0
        for col in (g_users, users):
            if col is None:
                continue
            for u in col.find({'organizationEmail': org_email}, {'email': 1, 'academic': 1}):
                a = u.get('academic') or {}
                batch = a.get('batch')
                if not batch or batch == 'test':
                    continue
                new_sem = current_semester_for(batch)
                if new_sem != a.get('currentSemester'):
                    col.update_one({'email': u['email']},
                                   {'$set': {'academic.currentSemester': new_sem}})
                    updated += 1
        return updated

    @app.route('/api/org/recompute-semesters', methods=['POST'])
    @org_admin_required
    def recompute_semesters_endpoint():
        """Org-admin manually triggers the recompute. Useful right after
        an academic-year boundary (early July) before the cron runs."""
        org_email = request._org_email
        n = _recompute_semesters_for_org(org_email)
        _audit_safe(admin_audit_col, 'org_recompute_sems', org_email,
                    {'updated': n}, actor=session.get('user_email'))
        return jsonify({'success': True, 'updated': n})

    @app.route('/api/admin/recompute-all-semesters', methods=['POST'])
    @super_admin_required
    def recompute_all_semesters_endpoint():
        """Super-admin runs across every org. Idempotent."""
        if organizations_col is None:
            return jsonify({'success': False, 'error': 'DB offline'}), 503
        total = 0
        per_org = {}
        for o in organizations_col.find({}):
            n = _recompute_semesters_for_org(o['email'])
            per_org[o['email']] = n
            total += n
        _audit_safe(admin_audit_col, 'admin_recompute_all_sems', '',
                    {'total': total, 'per_org': per_org})
        return jsonify({'success': True, 'updated': total, 'breakdown': per_org})

    # Auto-trigger once per process boot — cheap (only updates rows that
    # changed). On Render with a single worker this runs effectively once
    # per deploy. No external cron infrastructure needed.
    try:
        if organizations_col is not None:
            booted_at = datetime.utcnow()
            count_orgs = organizations_col.count_documents({})
            if count_orgs > 0:
                # Only run if it's been more than 12 hours since last boot-recompute
                # (don't spam the DB on rapid restarts).
                cache_doc = organizations_col.find_one({'_marker': 'sem_recompute'})
                last = cache_doc and cache_doc.get('ranAt')
                if not last or (booted_at - last).total_seconds() > 12 * 3600:
                    total_updated = 0
                    for o in organizations_col.find({}):
                        total_updated += _recompute_semesters_for_org(o['email'])
                    organizations_col.update_one(
                        {'_marker': 'sem_recompute'},
                        {'$set': {'_marker': 'sem_recompute', 'ranAt': booted_at, 'updated': total_updated}},
                        upsert=True,
                    )
                    if total_updated > 0:
                        print(f"✓ Boot-time semester recompute: {total_updated} students updated")
    except Exception as _e:
        print(f"⚠ Boot-time semester recompute failed: {_e}")

    # ─────────────────────────────────────────────────────────
    # Bulk Excel import
    # ─────────────────────────────────────────────────────────

    @app.route('/api/org/students/template.xlsx', methods=['GET'])
    @org_admin_required
    def students_xlsx_template():
        """Returns an .xlsx pre-populated with the org's branches/sections as dropdowns."""
        try:
            from openpyxl import Workbook
            from openpyxl.worksheet.datavalidation import DataValidation
        except ImportError:
            return jsonify({'error': 'openpyxl not installed on server.'}), 503

        org_email = request._org_email
        org = organizations_col.find_one({'email': org_email}) or {}
        branches = [b['code'] for b in (org.get('branches') or [])] or DEFAULT_BRANCHES
        sections = org.get('sections') or DEFAULT_SECTIONS
        batches = org.get('batches') or DEFAULT_BATCHES

        wb = Workbook()
        ws = wb.active
        ws.title = 'Students'
        headers = ['email', 'name', 'usn', 'batch', 'branch', 'section', 'rollNumber']
        ws.append(headers)
        # A few example rows to make it obvious how to fill.
        ws.append([f'student.example@{org.get("domain", "vvce.ac.in")}', 'Example Student',
                   '4VV23CI001', batches[-1] if batches else '2023',
                   branches[0] if branches else 'CSE', sections[0] if sections else 'A', '1'])

        # Reference sheet so dropdown cells don't bloat the file.
        ref = wb.create_sheet('_lookup')
        ref.append(['batches'] + list(batches))
        ref.append(['branches'] + list(branches))
        ref.append(['sections'] + list(sections))
        ref.sheet_state = 'hidden'

        if branches:
            dv_branch = DataValidation(type='list', formula1=f'=_lookup!$B$2:${chr(ord("A") + len(branches))}$2', allow_blank=True)
            dv_branch.add('E2:E2000')
            ws.add_data_validation(dv_branch)
        if sections:
            dv_section = DataValidation(type='list', formula1=f'=_lookup!$B$3:${chr(ord("A") + len(sections))}$3', allow_blank=True)
            dv_section.add('F2:F2000')
            ws.add_data_validation(dv_section)
        if batches:
            dv_batch = DataValidation(type='list', formula1=f'=_lookup!$B$1:${chr(ord("A") + len(batches))}$1', allow_blank=True)
            dv_batch.add('D2:D2000')
            ws.add_data_validation(dv_batch)

        # Auto-widen columns a bit.
        for col_letter, w in zip('ABCDEFG', (28, 22, 14, 10, 14, 10, 10)):
            ws.column_dimensions[col_letter].width = w

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)

        from flask import send_file
        return send_file(buf, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                         as_attachment=True, download_name='asanminds_student_import_template.xlsx')

    def _parse_uploaded_excel(file_storage, org):
        """Read uploaded .xlsx into list of dicts. Returns (rows, errors)."""
        try:
            from openpyxl import load_workbook
        except ImportError:
            return [], ['Server cannot parse Excel — openpyxl not installed.']
        try:
            wb = load_workbook(file_storage, data_only=True)
        except Exception as e:
            return [], [f'Could not read file: {e}']
        ws = wb.active
        rows_iter = ws.iter_rows(values_only=True)
        try:
            header = next(rows_iter)
        except StopIteration:
            return [], ['Empty workbook']
        col_idx = {str(h or '').strip().lower(): i for i, h in enumerate(header)}
        required = ['email', 'batch', 'branch', 'section']
        missing = [c for c in required if c not in col_idx]
        if missing:
            return [], [f'Missing required column(s): {", ".join(missing)}']

        domain = (org.get('domain') or '').strip().lower()
        valid_branches = {b['code'].upper() for b in (org.get('branches') or [])}
        valid_sections = {s.upper() for s in (org.get('sections') or [])}

        out = []
        errors = []
        for i, row in enumerate(rows_iter, start=2):
            if not row or all(c in (None, '') for c in row):
                continue
            def cell(name):
                idx = col_idx.get(name)
                return row[idx] if idx is not None and idx < len(row) else None
            email = (cell('email') or '')
            email = str(email).strip().lower() if email else ''
            if not email or '@' not in email:
                errors.append(f'Row {i}: invalid email "{email}"')
                continue
            if domain and domain != '*' and not email.endswith('@' + domain):
                errors.append(f'Row {i}: email "{email}" does not match @{domain}')
                continue
            branch = str(cell('branch') or '').strip().upper()
            if valid_branches and branch and branch not in valid_branches:
                errors.append(f'Row {i}: branch "{branch}" not in org branch list')
                continue
            section = str(cell('section') or '').strip().upper()
            if valid_sections and section and section not in valid_sections:
                errors.append(f'Row {i}: section "{section}" not in org section list')
                continue
            out.append({
                'email': email,
                'name': str(cell('name') or '').strip()[:120],
                'usn': str(cell('usn') or '').strip()[:30],
                'batch': str(cell('batch') or '').strip()[:10],
                'branch': branch,
                'section': section,
                'rollNumber': str(cell('rollNumber') or cell('roll') or '').strip()[:10],
            })
        return out, errors

    @app.route('/api/org/students/import-preview', methods=['POST'])
    @org_admin_required
    def students_import_preview():
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file uploaded.'}), 400
        org_email = request._org_email
        org = organizations_col.find_one({'email': org_email}) or {}
        rows, errors = _parse_uploaded_excel(request.files['file'], org)

        # Tag each row as new/existing/duplicate-in-file.
        seen = set()
        existing_emails = set()
        for col in (g_users, users):
            if col is None:
                continue
            for u in col.find({'email': {'$in': [r['email'] for r in rows]}}, {'email': 1}):
                existing_emails.add(u['email'])
        new = []
        update = []
        dup_in_file = []
        for r in rows:
            if r['email'] in seen:
                dup_in_file.append(r['email'])
                continue
            seen.add(r['email'])
            (update if r['email'] in existing_emails else new).append(r)

        # Cap check.
        cap = int(org.get('studentCap') or 0)
        current = sum(c.count_documents({'organizationEmail': org_email}) for c in (g_users, users) if c is not None)
        pending = invitations_col.count_documents({'organizationEmail': org_email, 'status': 'pending', 'role': 'student'}) if invitations_col is not None else 0
        seats_left = max(0, cap - current - pending)
        over_cap = max(0, len(new) - seats_left)
        if over_cap:
            errors.append(f'Seat cap exceeded: {over_cap} students will not be invited (cap {cap}, used {current + pending}).')

        return jsonify({
            'newCount': len(new),
            'updateCount': len(update),
            'duplicateInFile': dup_in_file,
            'errors': errors,
            'seatsLeft': seats_left,
            'sample': new[:5] + update[:5],
        })

    @app.route('/api/org/students/import', methods=['POST'])
    @org_admin_required
    def students_import_commit():
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file uploaded.'}), 400
        org_email = request._org_email
        org = organizations_col.find_one({'email': org_email}) or {}
        rows, errors = _parse_uploaded_excel(request.files['file'], org)
        if not rows:
            return jsonify({'success': False, 'errors': errors or ['No valid rows']}), 400

        # Cap check (hard).
        cap = int(org.get('studentCap') or 0)
        current = sum(c.count_documents({'organizationEmail': org_email}) for c in (g_users, users) if c is not None)
        pending = invitations_col.count_documents({'organizationEmail': org_email, 'status': 'pending', 'role': 'student'}) if invitations_col is not None else 0

        new_emails = []
        updated = 0
        invited = 0
        seen = set()
        existing_set = set()
        if g_users is not None:
            for u in g_users.find({'email': {'$in': [r['email'] for r in rows]}}, {'email': 1}):
                existing_set.add(u['email'])
        if users is not None:
            for u in users.find({'email': {'$in': [r['email'] for r in rows]}}, {'email': 1}):
                existing_set.add(u['email'])

        for r in rows:
            if r['email'] in seen:
                continue
            seen.add(r['email'])
            academic = {
                'batch': r['batch'], 'branch': r['branch'], 'section': r['section'],
                'usn': r['usn'], 'rollNumber': r['rollNumber'],
                'currentSemester': current_semester_for(r['batch']),
            }
            if r['email'] in existing_set:
                # Update existing user's academic fields + bind to org.
                for col in (g_users, users):
                    if col is None:
                        continue
                    col.update_one({'email': r['email']},
                                   {'$set': {'organizationEmail': org_email,
                                             'academic': academic,
                                             'role': 'student',
                                             'paidStatus': 'paid' if org.get('paid') else 'unpaid'}})
                updated += 1
            else:
                # Within cap?
                if current + pending + invited + 1 > cap:
                    errors.append(f"Skipped {r['email']} — seat cap ({cap}) reached.")
                    continue
                # Create invitation with prefilled academic data.
                if invitations_col is None:
                    continue
                token = secrets.token_hex(20)
                invitations_col.insert_one({
                    'email': r['email'],
                    'token': token,
                    'inviterEmail': session.get('user_email'),
                    'organizationEmail': org_email,
                    'role': 'student',
                    'status': 'pending',
                    'prefilled': {**r, 'currentSemester': academic['currentSemester']},
                    'createdAt': datetime.utcnow(),
                })
                link = request.url_root.rstrip('/') + '/invite/' + token
                _send_invite_email(r['email'], 'student', link, org.get('name', 'AsanMinds'))
                new_emails.append(r['email'])
                invited += 1

        _audit_safe(admin_audit_col, 'org_bulk_import', org_email,
                    {'invited': invited, 'updated': updated, 'errors': len(errors)},
                    actor=session.get('user_email'))
        return jsonify({
            'success': True,
            'invited': invited,
            'updated': updated,
            'errors': errors,
        })

    # ─────────────────────────────────────────────────────────
    # Org-scoped feedback / certificates / analytics / broadcast
    # ─────────────────────────────────────────────────────────

    def _emails_in_org(org_email):
        """Returns a set of all student emails belonging to this org."""
        out = set()
        for col in (g_users, users):
            if col is None:
                continue
            for u in col.find({'organizationEmail': org_email}, {'email': 1, '_id': 0}):
                if u.get('email'):
                    out.add(u['email'])
        return out

    @app.route('/api/org/feedback', methods=['GET'])
    @org_admin_required
    def org_feedback():
        org_email = request._org_email
        if feedback_col is None:
            return jsonify({'feedback': []})
        emails = _emails_in_org(org_email)
        if not emails:
            return jsonify({'feedback': []})
        rows = []
        # Build a name+picture lookup for the table rendering.
        name_pic = {}
        for col in (g_users, users):
            if col is None:
                continue
            for u in col.find({'organizationEmail': org_email}, {'email': 1, 'name': 1, 'picture': 1, '_id': 0}):
                name_pic[u['email']] = u
        for f in feedback_col.find({'email': {'$in': list(emails)}}).sort('submitted_at', -1).limit(500):
            f.pop('_id', None)
            u = name_pic.get(f.get('email', ''), {})
            f['name'] = u.get('name', '')
            f['picture'] = u.get('picture', '')
            rows.append(f)
        return jsonify({'feedback': rows})

    @app.route('/api/org/certificates', methods=['GET'])
    @org_admin_required
    def org_certificates():
        org_email = request._org_email
        emails = _emails_in_org(org_email)
        if not emails:
            return jsonify({'certificates': []})
        out = []
        for col in (cert_col, g_cert_col):
            if col is None:
                continue
            for c in col.find({'email': {'$in': list(emails)}}).sort('issuedAt', -1).limit(2000):
                c.pop('_id', None)
                out.append(c)
        out.sort(key=lambda c: c.get('issuedAt', ''), reverse=True)
        return jsonify({'certificates': out})

    @app.route('/api/org/analytics', methods=['GET'])
    @org_admin_required
    def org_analytics():
        """Same shape as super-admin analytics but scoped to this org's students."""
        org_email = request._org_email
        emails = _emails_in_org(org_email)
        if not emails:
            return jsonify({
                'poses': {'labels': [], 'values': [], 'label': 'Sessions'},
                'streaks': {'labels': [], 'values': [], 'label': 'Users'},
                'retention': {'labels': [], 'values': [], 'label': '% retained'},
                'signups': {'labels': [], 'values': [], 'label': 'Sign-ups'},
                'completion_by_branch': {'labels': [], 'values': [], 'label': '% complete'},
                'completion_by_section': {'labels': [], 'values': [], 'label': '% complete'},
            })

        all_users = []
        for col in (g_users, users):
            if col is None:
                continue
            for u in col.find({'organizationEmail': org_email}):
                u.pop('_id', None)
                all_users.append(u)

        today = datetime.utcnow().date()

        # Pose popularity (top 12).
        pose_totals = {}
        for u in all_users:
            for name, count in (u.get('completed_asanas') or {}).items():
                try:
                    pose_totals[name] = pose_totals.get(name, 0) + int(count or 0)
                except Exception:
                    pass
        top = sorted(pose_totals.items(), key=lambda x: -x[1])[:12]
        poses = {'labels': [n for n, _ in top], 'values': [c for _, c in top], 'label': 'Sessions'}

        # Streak distribution.
        buckets = [(0, '0'), (1, '1-2'), (3, '3-6'), (7, '7-13'), (14, '14-29'), (30, '30+')]
        bucket_counts = [0] * len(buckets)
        for u in all_users:
            activity = sorted(u.get('activity_log', []) or [])
            best = cur = 0
            prev = None
            for d in activity:
                try:
                    t = datetime.fromisoformat(d).date()
                except Exception:
                    continue
                if prev and (t - prev).days == 1:
                    cur += 1
                else:
                    cur = 1
                if cur > best:
                    best = cur
                prev = t
            for idx in range(len(buckets) - 1, -1, -1):
                if best >= buckets[idx][0]:
                    bucket_counts[idx] += 1
                    break
        streaks = {'labels': [b[1] for b in buckets], 'values': bucket_counts, 'label': 'Users'}

        # D1 / D7 / D14 / D30 retention.
        days_after = [1, 7, 14, 30]
        retention_pcts = []
        for d in days_after:
            eligible = retained = 0
            cutoff = (today - timedelta(days=d)).isoformat()
            for u in all_users:
                created = u.get('created_at')
                if hasattr(created, 'isoformat'):
                    ci = created.isoformat()[:10]
                elif isinstance(created, str):
                    ci = created[:10]
                else:
                    continue
                if ci > cutoff:
                    continue
                eligible += 1
                activity = u.get('activity_log') or []
                base = datetime.fromisoformat(ci).date()
                target_a = (base + timedelta(days=d - 1)).isoformat()
                target_b = (base + timedelta(days=d + 1)).isoformat()
                if any(target_a <= a <= target_b for a in activity):
                    retained += 1
            retention_pcts.append(round(retained / eligible * 100) if eligible else 0)
        retention = {'labels': [f'D{d}' for d in days_after], 'values': retention_pcts, 'label': '% retained'}

        # Sign-ups by week (last 12 weeks).
        weeks = []
        week_counts = []
        for i in range(11, -1, -1):
            wk_end = today - timedelta(days=i * 7)
            wk_start = wk_end - timedelta(days=6)
            weeks.append(wk_start.strftime('%d %b'))
            cnt = 0
            for u in all_users:
                created = u.get('created_at')
                if hasattr(created, 'isoformat'):
                    ci = created.isoformat()[:10]
                elif isinstance(created, str):
                    ci = created[:10]
                else:
                    continue
                if wk_start.isoformat() <= ci <= wk_end.isoformat():
                    cnt += 1
            week_counts.append(cnt)
        signups = {'labels': weeks, 'values': week_counts, 'label': 'Sign-ups'}

        # Completion percent by branch (% of pose-rule passes, very rough).
        # Cleaner: count of completed semesters per branch divided by enrolled.
        sems_done_by_branch = {}
        total_by_branch = {}
        sems_done_by_section = {}
        total_by_section = {}
        progress_emails = list(emails)
        cp_lookup = {}
        for col in (cp_col, g_cp_col):
            if col is None:
                continue
            for d in col.find({'email': {'$in': progress_emails}}, {'email': 1, 'progress': 1, '_id': 0}):
                cp_lookup[d['email']] = (d.get('progress') or {}).get('courses') or {}
        for u in all_users:
            a = u.get('academic') or {}
            br = a.get('branch') or 'unknown'
            sc = a.get('section') or 'unknown'
            done = sum(1 for c in (cp_lookup.get(u['email']) or {}).values() if c.get('completed'))
            total_by_branch[br] = total_by_branch.get(br, 0) + 1
            sems_done_by_branch[br] = sems_done_by_branch.get(br, 0) + done
            total_by_section[sc] = total_by_section.get(sc, 0) + 1
            sems_done_by_section[sc] = sems_done_by_section.get(sc, 0) + done

        def avg_pct(done_map, total_map):
            labels = sorted(total_map.keys())
            values = [round((done_map.get(k, 0) / max(1, total_map[k])) / 6 * 100) for k in labels]
            return {'labels': labels, 'values': values, 'label': '% complete'}

        return jsonify({
            'poses': poses,
            'streaks': streaks,
            'retention': retention,
            'signups': signups,
            'completion_by_branch': avg_pct(sems_done_by_branch, total_by_branch),
            'completion_by_section': avg_pct(sems_done_by_section, total_by_section),
        })

    @app.route('/api/org/broadcast', methods=['POST'])
    @org_admin_required
    def org_broadcast():
        """Push notification to (a) every active subscriber in this org, or
        (b) only the filtered set passed in `emails` (e.g., from the
        Students tab after applying a batch/branch filter)."""
        if not webpush_send:
            return jsonify({'success': False, 'error': 'Push not configured.'}), 503
        org_email = request._org_email
        data = request.get_json(silent=True) or {}
        title = (data.get('title') or 'A note from your coach').strip()[:80]
        body = (data.get('body') or '').strip()[:300]
        if not body:
            return jsonify({'success': False, 'error': 'body is required.'}), 400
        targets = data.get('emails')
        org_member_emails = _emails_in_org(org_email)
        if targets:
            # Restrict to people who actually belong to this org (defense in depth).
            targets = [e for e in targets if e in org_member_emails]
        else:
            targets = list(org_member_emails)
        delivered = 0
        failed = 0
        for em in targets:
            if webpush_send(em, title, body):
                delivered += 1
            else:
                failed += 1
        _audit_safe(admin_audit_col, 'org_broadcast', org_email,
                    {'title': title, 'attempted': len(targets), 'delivered': delivered},
                    actor=session.get('user_email'))
        return jsonify({'success': True, 'attempted': len(targets), 'delivered': delivered, 'failed': failed})

    # ─────────────────────────────────────────────────────────
    # Invitation acceptance — handled in the main /auth/google flow,
    # but we expose helpers here for clarity.
    # ─────────────────────────────────────────────────────────

    def consume_invitation_for(email):
        """Returns the latest pending invitation for this email (and marks it accepted), or None.
        Called from the /auth/google handler in app.py.
        """
        if invitations_col is None:
            return None
        em = (email or '').strip().lower()
        inv = invitations_col.find_one({'email': em, 'status': 'pending'}, sort=[('createdAt', -1)])
        if not inv:
            return None
        invitations_col.update_one({'_id': inv['_id']}, {'$set': {'status': 'accepted', 'acceptedAt': datetime.utcnow()}})
        return inv

    @app.route('/invite/<token>', methods=['GET'])
    def invite_landing(token):
        """Magic-link landing — verifies token, redirects to home with the invite remembered."""
        if invitations_col is None:
            return _invite_html('Database offline. Try again in a moment.', error=True)
        inv = invitations_col.find_one({'token': token, 'status': 'pending'})
        if not inv:
            return _invite_html('This invitation is invalid or has already been used.', error=True)
        # Stash token in session — /auth/google will consume it after Google sign-in.
        session['invite_token'] = token
        return _invite_html(
            f'You\'re invited to join as <b>{inv.get("role", "user").replace("_", " ")}</b>. '
            f'Sign in below with your Google account.',
            invite_email=inv.get('email', ''),
        )

    def _invite_html(message, error=False, invite_email=''):
        # Re-use the existing landing's Google sign-in UI by redirecting there
        # with a query param so the page shows the invitation context.
        from flask import redirect, url_for
        # Render a tiny standalone page that does the Google sign-in redirect.
        body = f"""<!DOCTYPE html>
<html><head><meta charset=utf-8><title>AsanMinds invitation</title>
<link rel=icon href=/assets/logo.png>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:wght@300;400&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>body{{margin:0;background:#F5F2EB;color:#14120E;font-family:Inter,system-ui,sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;padding:24px}}
.card{{background:#fff;border:1px solid #D4CCB8;border-radius:22px;padding:40px 36px;max-width:440px;width:100%;text-align:center}}
h1{{font-family:Fraunces,serif;font-size:32px;font-weight:300;margin:0 0 8px;letter-spacing:-0.02em}}
.kicker{{color:#C2552F;font-size:11px;letter-spacing:0.22em;text-transform:uppercase;font-weight:500}}
.msg{{color:#4A453B;font-size:14px;margin:18px 0 24px;line-height:1.5}}
a.btn{{display:inline-block;padding:14px 28px;background:#0F3D2E;color:#F5F2EB;text-decoration:none;border-radius:9999px;font-weight:500;font-size:14px}}
.err{{color:#C2552F}}
.email-hint{{color:#7A7364;font-size:12px;margin-top:18px}}
</style></head>
<body><div class=card>
<span class=kicker>Invitation</span>
<h1>Welcome to AsanMinds</h1>
<p class="msg {'err' if error else ''}">{message}</p>
{'' if error else f'<a class=btn href="/">Continue with Google</a>'}
{f'<p class="email-hint">Sign in with <b>{invite_email}</b> to accept</p>' if invite_email and not error else ''}
</div></body></html>"""
        from flask import make_response
        resp = make_response(body)
        resp.headers['Content-Type'] = 'text/html; charset=utf-8'
        return resp

    # Expose helper to the rest of app.py.
    return {
        'is_super_admin': _is_super_admin,
        'is_org_admin': _is_org_admin,
        'super_admin_required': super_admin_required,
        'org_admin_required': org_admin_required,
        'consume_invitation_for': consume_invitation_for,
        'send_welcome_email': _send_welcome_email,
        'TEST_ORG_EMAIL': TEST_ORG_EMAIL,
    }
