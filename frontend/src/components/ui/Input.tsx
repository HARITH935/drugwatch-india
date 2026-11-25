import { forwardRef, type InputHTMLAttributes } from "react";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  ({ className = "", ...props }, ref) => {
    return (
      <input
        ref={ref}
        // 40px tall, matching Button's default size (component-specs.md) - a search box and
        // its submit button must line up exactly, not just look close.
        className={`h-10 w-full rounded-(--radius-md) border border-border bg-card px-3 text-sm text-foreground placeholder:text-muted-foreground ${className}`}
        {...props}
      />
    );
  },
);
Input.displayName = "Input";
