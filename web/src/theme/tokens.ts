/** Numbers the code needs; colours and sizes live in tokens.css. */
export const motion = {
  rowStagger: 0.03,
  rowRise: 6,
  enter: { duration: 0.24, ease: [0.2, 0.8, 0.2, 1] as const },
  sweep: { duration: 0.7, ease: [0.3, 0.7, 0.1, 1] as const },
  swap: { duration: 0.16, ease: [0.4, 0, 0.2, 1] as const },
};

export const timing = {
  pollMs: 10000,
};

export const timeline = {
  /** pixels per day on the runway timeline */
  pxPerDay: 26,
  /** a wave is drawn at least this wide so a short window stays clickable */
  minWaveWidth: 18,
  /** days shown before the plan starts and after the last wave */
  paddingDays: 3,
  laneHeight: 56,
  axisHeight: 40,
};
