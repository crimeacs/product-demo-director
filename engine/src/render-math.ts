/** Pure frame/mix calculations shared by composition metadata and the renderer. */
export type TimedSegment = {
  kind: string;
  durSec: number;
  durFrames?: number;
  src?: string;
  transition?: 'cut' | 'xfade' | 'reveal' | 'push';
  transitionSec?: number;
  flash?: boolean;
  vo?: string;
  voSec?: number;
  sound?: boolean;
};

export function segmentFrames(segment: TimedSegment, fps: number): number {
  return Math.max(1, Math.round(segment.durFrames ?? segment.durSec * fps));
}

export function timelineLayout(segments: TimedSegment[], fps: number) {
  const frames = segments.map((segment) => segmentFrames(segment, fps));
  const fades = segments.map((segment, index) => {
    if (index === 0) return 0;
    const previous = segments[index - 1];
    const transition = segment.transition ?? (
      segment.flash || (segment.kind === 'clip' && previous.kind === 'clip'
        && segment.src && segment.src === previous.src) ? 'cut' : 'xfade'
    );
    // Even a very short insert must reach full opacity before its final picture frame.
    const span = Math.max(0, Math.round((segment.transitionSec ?? 0.3) * fps));
    return transition !== 'cut' ? Math.min(span, frames[index] - 1) : 0;
  });
  let cursor = 0;
  const rows = segments.map((_, index) => {
    const row = { start: cursor, frames: frames[index], fadeIn: fades[index],
      tail: fades[index + 1] ?? 0 };
    cursor += frames[index];
    return row;
  });
  return { rows, totalFrames: cursor };
}

export type Narration = { src: string; startAtSec?: number; durationSec?: number; volume?: number };
export type SpeechWindow = [number, number];

export function speechWindows(segments: TimedSegment[], fps: number, narration?: Narration | null): SpeechWindow[] {
  const { rows, totalFrames } = timelineLayout(segments, fps);
  const windows: SpeechWindow[] = [];
  segments.forEach((segment, index) => {
    if (!segment.vo && !segment.sound) return;
    const row = rows[index];
    const spokenFrames = !segment.sound && segment.voSec != null && segment.voSec > 0
      ? Math.min(row.frames, Math.max(1, Math.round(segment.voSec * fps))) : row.frames;
    windows.push([row.start, row.start + spokenFrames]);
  });
  if (narration?.src) {
    const start = Math.max(0, Math.round((narration.startAtSec ?? 0) * fps));
    const duration = narration.durationSec != null && narration.durationSec > 0
      ? Math.max(1, Math.round(narration.durationSec * fps)) : totalFrames - start;
    if (start < totalFrames) windows.push([start, Math.min(totalFrames, start + duration)]);
  }
  return windows;
}

const unit = (value: number) => Math.max(0, Math.min(1, value));

export function musicGain(frame: number, totalFrames: number, fps: number,
  windows: SpeechWindow[], volume: number, fadeOutSec: number): number {
  const ramp = Math.max(1, Math.round(0.3 * fps));
  let gain = 1;
  for (const [start, end] of windows) {
    const distance = Math.max(start - frame, frame - end, 0);
    gain = Math.min(gain, 0.45 + 0.55 * unit(distance / ramp));
  }
  const fadeIn = unit(frame / Math.max(1, Math.round(0.5 * fps)));
  const fadeFrames = Math.max(0, Math.round(Math.max(0, fadeOutSec) * fps));
  const lastFrame = Math.max(0, totalFrames - 1);
  const fadeSpan = Math.min(lastFrame, Math.max(1, fadeFrames - 1));
  const fadeOut = fadeFrames === 0 ? 1 : lastFrame === 0 ? 0
    : unit((lastFrame - frame) / fadeSpan);
  return Math.max(0, volume) * gain * fadeIn * fadeOut;
}

export type ClipFraming = {
  scale?: number; startScale?: number; endScale?: number;
  focusX?: number; focusY?: number; panX?: number; panY?: number;
  preserveFraming?: boolean;
};

export type SourcePlane = { left: number; top: number; width: number; height: number };
export type PercentRect = { x: number; y: number; width: number; height: number };
export type SourceDetail = {
  sourceRect: PercentRect;
  screenRect?: PercentRect;
  entranceSec?: number;
  radiusPx?: number;
  titleAlign?: 'left' | 'center';
};

/** Conservative optical widths; DOM checks also verify the project's actual font. */
export function detailTextWidth(text: string): number {
  return [...text].reduce((width, char) => width + (
    /\s/u.test(char) ? 0.27 : /[ilI1|.,'!:;]/u.test(char) ? 0.29 :
      /[MW@%&]/u.test(char) ? 0.9 : /[A-Z0-9]/u.test(char) ? 0.67 :
        /[^\u0000-\u024f]/u.test(char) ? 1 : 0.55
  ), 0);
}

function detailTextLines(text: string, width: number, fontSize: number): string[] | null {
  const words = text.trim().split(/\s+/u).filter(Boolean);
  const lines: string[] = [];
  for (const word of words) {
    if (detailTextWidth(word) * fontSize * 1.1 > width) return null;
    const last = lines[lines.length - 1];
    if (last && detailTextWidth(`${last} ${word}`) * fontSize * 1.1 <= width) lines[lines.length - 1] += ` ${word}`;
    else lines.push(word);
  }
  return lines;
}

/** Reserve copy outside the entire placement rectangle, including its arrival travel. */
export function detailTitleLayout(title: string, detail: SourceDetail, width: number, height: number) {
  const scale = Math.min(width / 1920, height / 1080);
  const screen = detail.screenRect ?? { x: 7, y: 25, width: 86, height: 55 };
  const left = width * screen.x / 100, availableWidth = width * screen.width / 100;
  const bandTop = 54 * scale, bandBottom = height * screen.y / 100 - 44 * scale;
  for (let size = 72; size >= 60; size--) {
    const fontSize = size * scale;
    const lines = detailTextLines(title, availableWidth, fontSize);
    const textHeight = (lines?.length ?? 0) * fontSize * 1.3;
    if (lines?.length && lines.length <= 2 && textHeight <= bandBottom - bandTop) {
      return { lines, fontSize, left, width: availableWidth, top: bandBottom - textHeight, height: textHeight };
    }
  }
  throw new Error('Detail title cannot fit above its plate at a readable size; shorten it or lower screenRect');
}

export function detailCaptionLayout(text: string, detail: SourceDetail, width: number, height: number,
  fontSize: number, captionTop?: number, captionBottom?: number) {
  const scale = Math.min(width / 1920, height / 1080);
  const screen = detail.screenRect ?? { x: 7, y: 25, width: 86, height: 55 };
  const left = 60 * scale, availableWidth = width - 2 * left;
  const textHeight = fontSize * 1.3 + 20 * scale;
  const bandTop = height * (screen.y + screen.height) / 100 + 36 * scale;
  const bandBottom = height - 12 * scale;
  const top = captionTop ?? (captionBottom == null ? bandTop : height - captionBottom - textHeight);
  const chunks = detailTextLines(text, availableWidth - 44 * scale, fontSize);
  if (!Number.isFinite(fontSize) || fontSize <= 0 || !Number.isFinite(top)
    || top < bandTop - 1e-6 || top + textHeight > bandBottom + 1e-6 || !chunks?.length) {
    throw new Error('Detail caption cannot fit below its plate; adjust screenRect, caption position, or text size');
  }
  return { chunks, fontSize, left, width: availableWidth, top, height: textHeight, paddingX: 22 * scale, paddingY: 10 * scale };
}

/** Fit a complete native source ROI inside a canvas box without a second cover crop. */
export function detailPlateGeometry(sourceWidth: number | undefined, sourceHeight: number | undefined,
  width: number, height: number, detail: SourceDetail) {
  if ([sourceWidth, sourceHeight, width, height].some(value => typeof value !== 'number'
    || !Number.isFinite(value) || value <= 0)) {
    throw new Error('Source detail requires verified positive source and output dimensions');
  }
  const validRect = (rect: PercentRect) => rect && [rect.x, rect.y, rect.width, rect.height].every(Number.isFinite)
    && rect.x >= 0 && rect.y >= 0 && rect.width > 0 && rect.height > 0
    && rect.x + rect.width <= 100 + 1e-8 && rect.y + rect.height <= 100 + 1e-8;
  const target = detail.screenRect ?? { x: 7, y: 25, width: 86, height: 55 };
  if (!validRect(detail.sourceRect) || !validRect(target)) {
    throw new Error('Source detail rectangles must stay wholly inside their source and output');
  }
  const sw = sourceWidth!, sh = sourceHeight!;
  const roi = { left: sw * detail.sourceRect.x / 100, top: sh * detail.sourceRect.y / 100,
    width: sw * detail.sourceRect.width / 100, height: sh * detail.sourceRect.height / 100 };
  const bounds = { left: width * target.x / 100, top: height * target.y / 100,
    width: width * target.width / 100, height: height * target.height / 100 };
  const scale = Math.min(bounds.width / roi.width, bounds.height / roi.height);
  const plate = { left: bounds.left + (bounds.width - roi.width * scale) / 2,
    top: bounds.top + (bounds.height - roi.height * scale) / 2,
    width: roi.width * scale, height: roi.height * scale };
  const video = { left: -roi.left * scale, top: -roi.top * scale, width: sw * scale, height: sh * scale };
  if (![scale, ...Object.values(plate), ...Object.values(video)].every(Number.isFinite)) {
    throw new Error('Source detail geometry cannot be represented at this size');
  }
  return { roi, bounds, plate, video, scale };
}

/** Leave room for caption margins and panel padding as authored text gets larger. */
export function captionCharacterBudget(width: number, fontSize: number): number {
  const available = Math.max(1, width - 120 - 44);
  const glyphWidth = Math.max(1, fontSize * 0.64 + 0.2);
  return Math.max(1, Math.min(46, Math.floor(available / glyphWidth)));
}

/**
 * The complete source plane as painted by centered CSS object-fit. Cover may
 * extend outside the output; contain may leave a letterbox. Display dimensions
 * already include source orientation and sample aspect ratio.
 */
export function sourcePlane(sourceWidth: number | undefined, sourceHeight: number | undefined,
  width: number, height: number, objectFit: 'cover' | 'contain' = 'cover'): SourcePlane {
  const w = Number.isFinite(width) && width > 0 ? width : 0;
  const h = Number.isFinite(height) && height > 0 ? height : 0;
  if (typeof sourceWidth !== 'number' || !Number.isFinite(sourceWidth) || sourceWidth <= 0
    || typeof sourceHeight !== 'number' || !Number.isFinite(sourceHeight) || sourceHeight <= 0
    || w === 0 || h === 0) {
    return { left: 0, top: 0, width: w, height: h };
  }
  const fit = objectFit === 'contain' ? Math.min : Math.max;
  const scale = fit(w / sourceWidth, h / sourceHeight);
  const fittedWidth = sourceWidth * scale;
  const fittedHeight = sourceHeight * scale;
  return { left: (w - fittedWidth) / 2, top: (h - fittedHeight) / 2,
    width: fittedWidth, height: fittedHeight };
}

/** Project an authored source-percent target into output-percent camera space. */
export function sourceFocus(plane: SourcePlane, width: number, height: number,
  focusX = 50, focusY = 50): { focusX: number; focusY: number } {
  const x = Number.isFinite(focusX) ? focusX : 50;
  const y = Number.isFinite(focusY) ? focusY : 50;
  // Do not clamp here: covered source points can legitimately sit outside the
  // output. The camera's existing bounds determine the nearest reachable pose.
  return {
    focusX: width > 0 ? 100 * (plane.left + plane.width * x / 100) / width : 50,
    focusY: height > 0 ? 100 * (plane.top + plane.height * y / 100) / height : 50,
  };
}

export function baseClipTransform(segment: ClipFraming, frame: number, duration: number,
  width: number, height: number) {
  if (segment.preserveFraming) return { s: 1, x: 0, y: 0 };
  const progress = unit(frame / Math.max(1, duration - 1));
  const eased = progress < 0.5 ? 2 * progress * progress : 1 - Math.pow(-2 * progress + 2, 2) / 2;
  const start = Math.max(1, segment.startScale ?? segment.scale ?? 1);
  const end = Math.max(1, segment.endScale ?? start);
  const s = start + (end - start) * eased;
  const focus = (value: number) => Math.max(1 / (2 * s), Math.min(1 - 1 / (2 * s), value / 100));
  const x = width / 2 - focus(segment.focusX ?? 50) * width * s
    + ((segment.panX ?? 0) * (1 - 0.55 * progress) / 100) * width;
  const y = height / 2 - focus(segment.focusY ?? 50) * height * s
    + ((segment.panY ?? 0) * (1 - 2 * progress) / 100) * height;
  return { s, x: Math.min(0, Math.max(width * (1 - s), x)),
    y: Math.min(0, Math.max(height * (1 - s), y)) };
}
