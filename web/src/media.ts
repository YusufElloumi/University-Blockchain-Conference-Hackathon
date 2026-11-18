// The site's photographs and hero film. Each photo has a 1920px file and, where the source clip
// was 4K, a 3840px file that only large or high-density screens download.
// Sources and licence: assets/media/CREDITS.md.

import summit from "./assets/media/summit.jpg";
import summit4k from "./assets/media/summit-4k.jpg";
import tennisFeet from "./assets/media/tennis-feet.jpg";
import tennisFeet4k from "./assets/media/tennis-feet-4k.jpg";
import wraps from "./assets/media/wraps.jpg";
import wraps4k from "./assets/media/wraps-4k.jpg";

export type Picture = { src: string; src4k?: string; alt: string };

export const PHOTOS = {
  summit: { src: summit, src4k: summit4k, alt: "A lone mountain summit against a dark sky, its snow picked out in blue" },
  tennisFeet: { src: tennisFeet, src4k: tennisFeet4k, alt: "A tennis player's feet and long shadow on the court, the shoes picked out in green" },
  wraps: { src: wraps, src4k: wraps4k, alt: "An athlete wrapping their hands before training, the wraps picked out in blue" },
} satisfies Record<string, Picture>;

export { default as heroPoster } from "./assets/media/hero-poster.jpg";
export { default as hero480 } from "./assets/media/hero-480.mp4";
export { default as hero720 } from "./assets/media/hero-720.mp4";
export { default as hero1080 } from "./assets/media/hero-1080.mp4";
export { default as hero2160 } from "./assets/media/hero-2160.mp4";
