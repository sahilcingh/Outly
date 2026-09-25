"use client";

import { motion, AnimatePresence, type Variants, type HTMLMotionProps } from "motion/react";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

export const EASE = [0.22, 1, 0.36, 1] as const;

export const fadeUp: Variants = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5, ease: EASE } },
};

export const staggerContainer: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.08, delayChildren: 0.04 } },
};

/** Fades/slides its children in once on mount. Use for page headers, form panels, cards. */
export function Reveal({
  children,
  delay = 0,
  ...rest
}: HTMLMotionProps<"div"> & { delay?: number }) {
  return (
    <motion.div
      initial="hidden"
      animate="show"
      variants={fadeUp}
      transition={{ delay }}
      {...rest}
    >
      {children}
    </motion.div>
  );
}

/** Wraps a list; children should be <StaggerItem> so they cascade in. */
export function StaggerList({ children, ...rest }: HTMLMotionProps<"div">) {
  return (
    <motion.div initial="hidden" animate="show" variants={staggerContainer} {...rest}>
      {children}
    </motion.div>
  );
}

export function StaggerItem({ children, ...rest }: HTMLMotionProps<"div">) {
  return (
    <motion.div variants={fadeUp} {...rest}>
      {children}
    </motion.div>
  );
}

/** Cross-fades route content on client-side navigation. Wrap the layout's <main> children. */
export function PageTransition({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  return (
    <AnimatePresence mode="wait" initial={false}>
      <motion.div
        key={pathname}
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -10 }}
        transition={{ duration: 0.22, ease: EASE }}
      >
        {children}
      </motion.div>
    </AnimatePresence>
  );
}

/** Mount/unmount fade+scale for content that appears conditionally (results, banners). */
export function PopIn({ children, ...rest }: HTMLMotionProps<"div">) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: -8, scale: 0.98 }}
      transition={{ duration: 0.35, ease: EASE }}
      {...rest}
    >
      {children}
    </motion.div>
  );
}

export { AnimatePresence, motion };
