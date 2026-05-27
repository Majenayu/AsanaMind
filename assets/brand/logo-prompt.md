# AsanMinds (Sunday) — Logo Generation Prompts

Use these in any AI image tool — Midjourney, DALL-E, Ideogram,
Stable Diffusion, Adobe Firefly, Recraft. Pick the one that
matches your tool. The strongest results come from Ideogram and
Recraft because they handle clean vector-style logos best.

The brand colours and aspect-ratio rules are baked in so the
output blends with the existing site.

---

## 1. Master prompt — the "Awakened Lotus" mark

> Minimalist logo design for "Sunday" by AsanMinds, an AI yoga
> coaching app. A single upright lotus petal silhouette in cream
> (#F5F2EB) with a saffron-gold (#E0A23F) inner flame shape
> nested inside it, all centred on a deep forest-green (#0F3D2E)
> rounded square tile with 14px radius. Two smaller darker
> teal-green leaves flank the central petal at the base.
> A small forest-green dot sits low inside the flame as a bindu.
> A delicate single saffron hairline stroke runs across the bottom
> like a yoga mat. Clean geometric shapes, no gradients, no shadows,
> no text. Symmetrical. Premium minimalism. Suitable for a 64x64
> app icon. Vector style. Square format. Flat design.

Negative prompts (if your tool supports them):
> realistic, photographic, 3D, gradient, drop shadow, complex,
> text, letters, watermark, busy, ornate, neon, glow

---

## 2. Variation — Seated meditator (Concept A from earlier)

> Minimalist app icon for "Sunday" yoga coaching. Clean geometric
> silhouette of a person seated in lotus / padmasana position,
> rendered in cream (#F5F2EB) on a forest-green (#0F3D2E) rounded
> square tile. Above the meditator's head, a thin saffron-gold
> (#E0A23F) sunrise arc. A single saffron dot at the third-eye
> position. Symmetrical, flat, no gradients, no text. Premium
> wellness brand aesthetic. 1:1 square. Vector logo style.

---

## 3. Variation — Geometric lotus (top-down)

> Minimalist top-down geometric lotus mandala logo for an AI yoga
> app called Sunday. Five outer cream petals (#F5F2EB) and five
> smaller inner sage-green petals (#C7DBCE) arranged radially on
> a forest-green (#0F3D2E) rounded square tile, with a saffron-gold
> (#E0A23F) circular bindu at the centre containing a tiny dark
> centre point. Symmetrical, flat, no shadows, no gradients, no
> text. App icon style. 1:1 square.

---

## 4. Wordmark lockup — for landing page header

> Horizontal logo lockup. Left side: a small cream lotus-petal
> mark on a forest-green (#0F3D2E) rounded square tile, with
> a saffron-gold (#E0A23F) flame inside. Right side, two lines
> of italic serif typography reading "sunday" (large, italic,
> Fraunces or Playfair Display, weight 300) above a small
> all-caps spaced sans-serif eyebrow reading "ASANMINDS". Cream
> off-white (#F5F2EB) background. Text in deep ink charcoal
> (#14120E). Premium editorial brand aesthetic. Aspect ratio 4:1.
> Flat design, no shadows.

---

## 5. Open-Graph card — for social shares (1200x630)

> Editorial social-media share card for an AI yoga coaching
> brand called Sunday by AsanMinds. Cream paper background
> (#F5F2EB). Large lotus-and-flame logo mark on the left third,
> set on a deep forest-green rounded square. On the right
> two-thirds: italic serif typography in deep ink reading
> "sunday" extra-large, with "ASANMINDS" small all-caps spaced
> beneath. Below that, the tagline "AI yoga that watches,
> listens, and teaches you back." in lighter italic serif.
> Soft saffron-gold radial blob in the upper-right corner,
> soft terracotta blob in the lower-left. Premium minimal,
> warm editorial feel, like a yoga magazine. Aspect ratio
> 1200:630.

---

## Brand colour palette (always include these in the prompt)

| Role             | Hex      | Description                  |
|------------------|----------|------------------------------|
| Cream paper      | #F5F2EB  | Background, off-white        |
| Forest           | #0F3D2E  | Brand primary, deep green    |
| Forest soft      | #1F5A44  | Side leaves, secondary       |
| Saffron flame    | #E0A23F  | The brand's eye-light        |
| Terracotta       | #C2552F  | Accent, sparingly            |
| Ink              | #14120E  | Body text                    |

## Typography pairing (when wordmark is shown)

- Display / wordmark: **Fraunces** (italic, weight 300), or
  Playfair Display, or Georgia as a safe fallback.
- Eyebrow / supporting: **Inter** (weight 500, all caps,
  letter-spacing 0.22em).

---

## Tips for best AI generation results

1. Run the prompt at 1024x1024 or larger so detail survives.
2. Generate 4 variants per prompt, pick the cleanest.
3. Bring the chosen one into Recraft / Illustrator / Figma and
   trace into clean vector — AI raster output usually has soft
   edges that need a vector pass for production.
4. Then export back to PNG at 192x192 and 512x512 for the PWA
   icon slots in `/manifest.json`.
5. Check the result at 16x16 — if it muddies, simplify the
   inner detail (drop the bindu or the side leaves).
