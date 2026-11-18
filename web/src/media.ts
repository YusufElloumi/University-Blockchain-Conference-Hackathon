// The site's photographs and hero film. Each photo has a 1920px file and, where the source clip
// was 4K, a 3840px file that only large or high-density screens download.
// Sources and licence: assets/media/CREDITS.md.

import barbell from "./assets/media/barbell.jpg";
import dribble from "./assets/media/dribble.jpg";
import dribble4k from "./assets/media/dribble-4k.jpg";
import duoBack from "./assets/media/duo-back.jpg";
import duoBack4k from "./assets/media/duo-back-4k.jpg";
import duoStreet from "./assets/media/duo-street.jpg";
import duoStreet4k from "./assets/media/duo-street-4k.jpg";
import pedal from "./assets/media/pedal.jpg";
import silhouette from "./assets/media/silhouette.jpg";
import silhouette4k from "./assets/media/silhouette-4k.jpg";
import stretch from "./assets/media/stretch.jpg";
import stretch4k from "./assets/media/stretch-4k.jpg";
import tennisFeet from "./assets/media/tennis-feet.jpg";
import tennisFeet4k from "./assets/media/tennis-feet-4k.jpg";
import trackLanes from "./assets/media/track-lanes.jpg";
import trackLanes4k from "./assets/media/track-lanes-4k.jpg";
import wraps from "./assets/media/wraps.jpg";
import wraps4k from "./assets/media/wraps-4k.jpg";

export type Picture = { src: string; src4k?: string; alt: string };

export const PHOTOS = {
  barbell: { src: barbell, alt: "A lifter standing over a loaded barbell, lit from behind" },
  dribble: { src: dribble, src4k: dribble4k, alt: "A basketball player dribbling low on an outdoor court" },
  duoBack: { src: duoBack, src4k: duoBack4k, alt: "Two runners side by side, seen from behind in morning light" },
  duoStreet: { src: duoStreet, src4k: duoStreet4k, alt: "Two people running together across a city bridge" },
  pedal: { src: pedal, alt: "A cyclist's foot pressing down on the pedal" },
  silhouette: { src: silhouette, src4k: silhouette4k, alt: "The silhouette of a runner at sunrise" },
  stretch: { src: stretch, src4k: stretch4k, alt: "The silhouette of an athlete stretching against the sky" },
  tennisFeet: { src: tennisFeet, src4k: tennisFeet4k, alt: "A tennis player's feet and long shadow on the court" },
  trackLanes: { src: trackLanes, src4k: trackLanes4k, alt: "A runner alone on numbered track lanes" },
  wraps: { src: wraps, src4k: wraps4k, alt: "An athlete wrapping their hands before training" },
} satisfies Record<string, Picture>;

export { default as heroPoster } from "./assets/media/hero-poster.jpg";
export { default as hero480 } from "./assets/media/hero-480.mp4";
export { default as hero720 } from "./assets/media/hero-720.mp4";
export { default as hero1080 } from "./assets/media/hero-1080.mp4";
export { default as hero2160 } from "./assets/media/hero-2160.mp4";
