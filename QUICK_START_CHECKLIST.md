# Quick Start Checklist - Microsoft Agents League

## 🚨 DO THIS TODAY (Day 1)

### Setup Free Accounts (1 hour total)
- [ ] Azure for Students: https://azure.microsoft.com/free/students/
  - Save your subscription ID: ____________________
  - Save your resource group name: ____________________

- [ ] M365 Developer: https://developer.microsoft.com/microsoft-365/dev-program
  - Save your tenant ID: ____________________
  - Save your app client ID: ____________________

- [ ] GitHub Copilot: https://education.github.com/pack
  - Verify student status: [ ]
  - Install VS Code extension: [ ]

- [ ] Microsoft Foundry: https://foundry.microsoft.com/
  - Access granted: [ ]

### Deploy Azure OpenAI (30 minutes)
- [ ] Create Azure OpenAI resource
- [ ] Deploy gpt-4o-mini model
- [ ] Copy endpoint URL: ____________________
- [ ] Copy API key: ____________________
- [ ] Test with sample API call: [ ]

### Update .env File
```bash
# Add these to your .env
AZURE_OPENAI_KEY=your_key_here
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=asanminds-coach
MS_APP_ID=your_m365_app_id
MS_APP_SECRET=your_m365_app_secret
```

---

## 📅 7-Day Sprint Schedule

### Day 1 (Today) - Setup ✅
- [x] Read CONTEST_UPGRADE_GUIDE.md
- [ ] Complete account setups above
- [ ] Clone repo, create contest branch
- [ ] Test Azure OpenAI connection

### Day 2 - Azure Integration 🔧
- [ ] Create azure_ai_coach.py
- [ ] Update app.py to use Azure OpenAI
- [ ] Test reasoning agent locally
- [ ] Deploy to Render/Azure
- [ ] Verify production works

### Day 3 - M365 Integration 💼
- [ ] Register Azure AD app
- [ ] Create teams_bot.py
- [ ] Add M365 routes to app.py
- [ ] Test Teams notifications
- [ ] Test Outlook calendar

### Day 4 - Documentation 📝
- [ ] Use Copilot to generate 2-3 new features
- [ ] Screenshot Copilot in action
- [ ] Create architecture diagram
- [ ] Update README with Microsoft badges
- [ ] Write copilot_generated_features.md

### Day 5 - Demo Video 🎬
- [ ] Write video script (use template in guide)
- [ ] Record screen demos (OBS Studio)
- [ ] Record voiceover (Audacity)
- [ ] Edit video (DaVinci Resolve)
- [ ] Upload to YouTube
- [ ] Share unlisted link with team

### Day 6 - Polish & Test 🧪
- [ ] Add Azure App Insights
- [ ] Test all features end-to-end
- [ ] Write CONTEST_SUBMISSION.md
- [ ] Create team Microsoft Learn profiles
- [ ] Final README polish
- [ ] Check all links work

### Day 7 - Submit & Promote 🚀
- [ ] Submit to contest platform
- [ ] Post to Discord with intro
- [ ] Engage with 5+ other projects
- [ ] Share on LinkedIn/Twitter
- [ ] Celebrate! 🎉

---

## ⚠️ Critical Must-Haves for Submission

1. **Azure OpenAI integrated** (not OpenRouter) ✅
2. **M365 integration shown** (Teams OR Outlook) ✅
3. **GitHub Copilot documented** (screenshots) ✅
4. **Architecture diagram** (shows all 3 tools) ✅
5. **Demo video** (<5 min, on YouTube/Vimeo) ✅
6. **Public GitHub repo** (with updated README) ✅
7. **All team members** (Microsoft Learn profiles) ✅

---

## 💰 Cost Tracker (Should Stay $0)

| Service | Used | Cost |
|---------|------|------|
| Azure OpenAI | __ tokens | $__ / $100 free |
| M365 Developer | Day __ / 90 | $0 |
| GitHub Copilot | Active | $0 (student) |
| MongoDB Atlas | __ MB / 512MB | $0 |
| Render.com | __ hrs / 750 | $0 |

**Total Spent: $0** ✅

---

## 🆘 Emergency Contacts

**Team Coordinator:** _____________________
**Submission Owner:** _____________________
**Discord Username:** _____________________

**Deadline:** June 14, 2026, 11:59 PM PT
**Days Remaining:** ___

---

## 📊 Current Status

**Overall Progress:** ___/100%

**Score Estimate:** ___/100
- Accuracy: ___/20
- Reasoning: ___/20
- Creativity: ___/15
- UX: ___/15
- Reliability: ___/20
- Community: ___/10

**Target:** 95+

---

**Next Action:** ________________________________
**Blockers:** ___________________________________
**Help Needed:** ________________________________
