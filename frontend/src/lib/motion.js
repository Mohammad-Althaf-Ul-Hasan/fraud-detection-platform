// Spring presets for consistent motion feel across the app
export const spring = {
  fast:    { type: "spring", stiffness: 500, damping: 35, mass: 0.6 },
  base:    { type: "spring", stiffness: 400, damping: 32, mass: 0.8 },
  slow:    { type: "spring", stiffness: 220, damping: 28, mass: 1.0 },
  gentle:  { type: "spring", stiffness: 160, damping: 24, mass: 1.2 },
};

export const fadeIn = {
  initial: { opacity: 0 },
  animate: { opacity: 1, transition: { duration: 0.18, ease: "easeOut" } },
  exit:    { opacity: 0, transition: { duration: 0.12, ease: "easeIn" } },
};

export const slideUp = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0, transition: spring.base },
  exit:    { opacity: 0, y: -4, transition: { duration: 0.12 } },
};

export const slideDown = {
  initial: { opacity: 0, y: -8 },
  animate: { opacity: 1, y: 0, transition: spring.fast },
  exit:    { opacity: 0, y: 8, transition: { duration: 0.12 } },
};

export const rowEnter = {
  initial: { opacity: 0, y: -4 },
  animate: { opacity: 1, y: 0, transition: { duration: 0.15, ease: "easeOut" } },
};

export const panelScale = {
  initial: { opacity: 0, scale: 0.96, y: -8 },
  animate: { opacity: 1, scale: 1, y: 0, transition: spring.base },
  exit:    { opacity: 0, scale: 0.98, y: -4, transition: { duration: 0.1 } },
};