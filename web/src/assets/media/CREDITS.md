# Media credits

All footage and stills in this folder come from Mixkit (https://mixkit.co) clips whose page shows the
**Mixkit Stock Video Free License**. Clips under Mixkit's **Restricted License** were deliberately not used
(several good ones were rejected for that reason, including two boxing silhouettes and a jump-rope clip).
Stills are single frames taken from the clips. The licence label on each page was checked on 2026-11-18.

| File | Source clip (page: `https://mixkit.co/free-stock-video/<name>/`) | Source quality |
|---|---|---|
| `hero-2160.mp4`, `hero-1080.mp4`, `hero-720.mp4`, `hero-480.mp4`, `hero-poster.jpg` | A 14.6-second cut of six clips, in order: `man-bandaging-his-hand-before-boxing-4596`, `steps-of-a-person-jogging-outside-40765`, `silhouette-of-a-runner-in-the-city-608`, `man-throwing-barbells-to-the-floor-40250`, `basketball-player-dribbling-ball-744`, `man-and-woman-jogging-together-on-the-street-40881` | 4K, except the barbell shot (1080p, upscaled) |
| `wraps.jpg`, `wraps-4k.jpg` | `man-bandaging-his-hand-before-boxing-4596` | 4K |
| `tennis-feet.jpg`, `tennis-feet-4k.jpg` | `tennis-players-feet-875` | 4K |
| `stretch.jpg`, `stretch-4k.jpg` | `silhouette-of-woman-stretching-her-arms-780` | 4K |
| `dribble.jpg`, `dribble-4k.jpg` | `basketball-player-dribbling-ball-744` | 4K |
| `duo-street.jpg`, `duo-street-4k.jpg` | `man-and-woman-jogging-together-on-the-street-40881` | 4K |
| `duo-back.jpg`, `duo-back-4k.jpg` | `man-and-woman-jogging-through-a-park-in-the-city-40754` | 4K |
| `track-lanes.jpg`, `track-lanes-4k.jpg` | `woman-running-fast-on-a-running-track-32792` | 4K |
| `silhouette.jpg`, `silhouette-4k.jpg` | `silhouette-of-a-runner-in-the-city-608` | 4K |
| `barbell.jpg` | `man-throwing-barbells-to-the-floor-40250` | 1080p only |
| `pedal.jpg` | `cyclist-places-his-foot-on-the-pedal-and-starts-to-40891` | 1080p only (not placed on a page yet) |

How it is served: every photo has a 1920px file, and 4K sources also have a 3840px file that only large or
high-density screens download (`srcset` in `Photo`, `web/src/sitekit.tsx`). The film has four sizes; the browser
picks one by screen width, so phones get the 1.6 MB file and only screens wider than 2400px get the 18 MB 4K file.
The colour footage is shown in black and white by a CSS filter (`.photo img`, `.film video` in `styles.css`),
not baked into the files. The file list and descriptions used by the pages are in `web/src/media.ts`.

`../logo-mark.png` and `../favicon.png` were made from the team's own logo artwork (black background removed).
