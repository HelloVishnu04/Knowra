# Kivo AI — Less busywork. More progress.

A 30-second, music-led SaaS promotional concept, authored with editable React/Remotion scenes. 16:9, 30 fps. The soundtrack is an original synthesized composition at 120 BPM. This cut uses on-screen messaging and music, with no spoken narration.

## Deliverables

- `output/Kivo-AI-Promo-30s.mp4`: Full HD playback/share version.
- `output/Kivo-AI-Promo-30s-4K.mp4`: 3840 × 2160 master.
- `output/final-review-1.jpg` and `final-review-2.jpg`: one sample from every second of the encoded Full HD file.
- `output/quality-report.json`: stream timing, audio peak, and all-frame blank/decode checks.
- `output/audio-report.json`: original score and cue timings.

## Creative treatment

The story moves from disconnected work to a unified workspace, then demonstrates requests being routed, a sales pipeline being updated, and a project risk being flagged for review. End card holds from 27–30 seconds. The screens are original illustrative UI, not screenshots of Kivo's current application. Alex Morgan and Acme Studio are fictional demonstration data. Dark green, mint, and warm white are this video's art direction, not a claim about official brand guidelines.

## Timing

| Seconds | Scene |
|---|---|
| 0–4 | Your business. In motion. |
| 4–7 | Too many tools. Too little flow. |
| 7–12 | One connected workspace. |
| 12–14.5 | Requests routed. |
| 14.5–17 | Pipelines updated. |
| 17–19 | Risks flagged. |
| 19–24 | Focus on what's next. |
| 24–27 | Less busywork. More progress. |
| 27–30 | Kivo logo, book a demo, kivo.ai. |

Each beat is 15 frames. Reveal/action cues occur at frames 210, 360, 435, 510, 570, 720, 765 and 810. Score and video are 30 seconds, with a short audio fade at the end and no early CTA fade.

## Edit and render

Requires Node.js and the locked npm dependencies. Install with `npm ci`, then `npm run studio`. Render Full HD with `npm run render`; render 4K with `node render.mjs 4k`. The renderer uses Remotion's bundled browser. The score-generation and QA scripts require Python, NumPy and Pillow.

Main animation: `src/KivoPromo.tsx`. Composition: `src/index.tsx`. Music: `make_audio.py` and `public/kivo-score.wav`.

## Sources and assets

- Company/product basis: https://www.kivo.ai/ and https://www.kivo.ai/aboutus and https://www.kivo.ai/products
- Official logo: https://www.kivo.ai/images/kivo_new_home_logo.svg (downloaded for this Kivo promotional concept).
- Typeface: Manrope, distributed through Google Fonts under the SIL Open Font License; license included in `public/Manrope-OFL.txt`.
- All interface drawings, geometric graphics, animation and music were created for this project. No stock footage, customer testimonials, performance metrics, or paid samples are used.

The project uses Remotion. Its software license is separate from the media assets; consult https://www.remotion.dev/license for the terms applicable to your organization.
