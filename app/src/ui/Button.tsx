import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { cx } from "./cx";

export type ButtonVariant = "primary" | "secondary" | "ghost";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: "sm" | "md";
  /** Leading icon (decorative; the label carries the meaning). */
  icon?: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", icon, className, children, type = "button", ...rest },
  ref,
) {
  return (
    <button ref={ref} type={type} className={cx("btn", `btn--${variant}`, `btn--${size}`, className)} {...rest}>
      {icon && (
        <span className="btn__icon" aria-hidden="true">
          {icon}
        </span>
      )}
      {children}
    </button>
  );
});

export interface IconButtonProps extends Omit<ButtonProps, "icon" | "children"> {
  /** Accessible name; also shown as the native tooltip unless `title` is given. */
  label: string;
  children: ReactNode;
}

/** Square icon-only button with a 40 px hit area. */
export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { label, variant = "ghost", size = "md", className, children, type = "button", title, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      aria-label={label}
      title={title ?? label}
      className={cx("btn", "btn--icon", `btn--${variant}`, `btn--${size}`, className)}
      {...rest}
    >
      <span className="btn__icon" aria-hidden="true">
        {children}
      </span>
    </button>
  );
});
