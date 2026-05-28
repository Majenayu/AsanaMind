# Converting the Research Paper and Patent to Other Formats

Both `research-paper.md` and `patent-application.md` are written in
GitHub-Flavoured Markdown with YAML front-matter. They convert cleanly
to PDF, DOCX, LaTeX, and HTML using **Pandoc**.

## 1. Install Pandoc + LaTeX (one-time)

**Windows.** Install Pandoc from <https://pandoc.org/installing.html>
and TinyTeX (lightweight LaTeX) from <https://yihui.org/tinytex/>:

```cmd
choco install pandoc
choco install miktex
```

**macOS.**

```bash
brew install pandoc
brew install --cask mactex-no-gui
```

**Linux.**

```bash
sudo apt install pandoc texlive-xetex texlive-fonts-recommended
```

## 2. Quick conversion commands

Run from `docs/research/` directory:

### To PDF (looks like a real journal paper)

```bash
pandoc research-paper.md -o research-paper.pdf \
  --pdf-engine=xelatex \
  --variable mainfont="Times New Roman" \
  --variable fontsize=11pt \
  --variable geometry:margin=1in \
  --toc

pandoc patent-application.md -o patent-application.pdf \
  --pdf-engine=xelatex \
  --variable mainfont="Times New Roman" \
  --variable fontsize=11pt \
  --variable geometry:margin=1in
```

### To Microsoft Word (.docx)

```bash
pandoc research-paper.md -o research-paper.docx
pandoc patent-application.md -o patent-application.docx
```

### To IEEE LaTeX template (for direct conference submission)

```bash
pandoc research-paper.md -o research-paper.tex --standalone
```

Then drop the generated `.tex` body into the IEEE
`IEEEtran.cls` skeleton (download from
<https://www.ieee.org/conferences/publishing/templates.html>).

### To plain HTML (for sharing)

```bash
pandoc research-paper.md -o research-paper.html --standalone --toc
```

## 3. IEEE-Style PDF (recommended for conference submission)

For a tighter IEEE two-column look, save this as
`ieee-style.tex` in the same folder:

```latex
\documentclass[10pt,conference]{IEEEtran}
\usepackage{cite}
\usepackage{amsmath}
\usepackage{graphicx}
\usepackage{hyperref}
$if(title)$\title{$title$}$endif$
$for(author)$\author{\IEEEauthorblockN{$author.name$}\IEEEauthorblockA{$author.affiliation$\\$author.email$}}$endfor$
\begin{document}
\maketitle
$if(abstract)$\begin{abstract}$abstract$\end{abstract}$endif$
$if(keywords)$\begin{IEEEkeywords}$for(keywords)$$keywords$$sep$, $endfor$\end{IEEEkeywords}$endif$
$body$
\end{document}
```

Then convert with the template:

```bash
pandoc research-paper.md -o research-paper-ieee.pdf \
  --template=ieee-style.tex \
  --pdf-engine=xelatex
```

## 4. Patent submission (Indian Patent Office)

The IPO accepts e-filings in **PDF only**. Use:

```bash
pandoc patent-application.md -o patent-application.pdf \
  --pdf-engine=xelatex \
  --variable mainfont="Times New Roman" \
  --variable fontsize=12pt \
  --variable geometry:a4paper,margin=1in \
  --number-sections=false
```

Then on the IPO e-filing portal (<https://ipindiaonline.gov.in>):

1. Register as an applicant.
2. Upload Form 1 (Application for Grant of Patent) — generated on
   the portal.
3. Upload this PDF as the **Form 2** (Complete Specification).
4. Upload Form 5 (Declaration of Inventorship).
5. Upload drawings (separate PDF, A4 line drawings of Figures 1–4).
6. Pay the fee (₹1,600 individual / Startup; ₹4,000 small entity;
   ₹8,000 large entity).

Provisional vs Complete: if you want 12 months of breathing room
to refine claims, file a **Provisional Specification** first
(₹1,600). You then have exactly 12 months to file the Complete
Specification or the application lapses.

## 5. Pre-submission checklist

- [ ] **Author affiliations** filled in (replace `[Co-author 2]`,
      `[Co-author 3]` placeholders, or remove).
- [ ] **Pilot data** populated in Section VI of the research paper.
- [ ] **Patent applicant address** filled in (Form 2 header).
- [ ] **Drawings drafted** as A4 line drawings (Figures 1–4 in
      patent; system architecture in research paper).
- [ ] **Prior-art search** completed via:
  - <https://patents.google.com>
  - <https://ipindiaservices.gov.in/publicsearch/>
  - <https://worldwide.espacenet.com>
- [ ] **Patent agent reviewed** the claims (recommended; not
      legally mandatory but every claim word matters in
      enforcement).
- [ ] **Confidentiality** maintained until filing — public
      disclosure (e.g., the live URL, GitHub repo) before filing
      can be a *novelty bar* in some jurisdictions. India has a
      **12-month grace period** for the inventor's own disclosure
      under §31, but other jurisdictions (EPC, Japan) do not.
      File first, then publish the paper.
- [ ] **PCT or convention application?** If you want
      international protection, file a PCT application within 12
      months of the Indian filing date for a global priority
      claim.

## 6. Suggested submission targets

**Research paper** — pick one based on fit:

- **IEEE COMPSAC 2026** — Computer Software and Applications,
  good fit for system-paper. Deadline typically March.
- **ACM CHI Late-Breaking Work** — if you can run the user study
  in Section VI.C in time.
- **NeurIPS 2026 Datasets & Benchmarks** — if you release the rule
  sets and a labelled dataset.
- **MDPI Healthcare** — open access, fast turnaround, good fit
  given the Borthakur 2023 precedent.

**Patent** — file in this order:

1. Indian Provisional (₹1,600, 12 months grace).
2. Indian Complete Specification within 12 months.
3. PCT application if you want international protection (within
   12 months of Provisional).
4. Designated national phase entries (US, EP, JP, KR) within 30
   months of Provisional.

Total cost for full international coverage: ₹2–3 lakh in fees plus
~₹50,000–1 lakh in agent fees per jurisdiction. For a single-
country (India only) filing: ~₹15,000 all-in.
