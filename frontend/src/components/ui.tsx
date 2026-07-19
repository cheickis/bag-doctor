import React, { forwardRef } from "react";

const classes = (...values: Array<string | false | null | undefined>) => values.filter(Boolean).join(" ");

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "default" | "secondary" | "ghost" | "danger" };
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(({ className, variant = "default", ...props }, ref) =>
  <button ref={ref} className={classes("ui-button", `ui-button-${variant}`, className)} {...props} />
);
Button.displayName = "Button";

export function Card({ className, ...props }: React.HTMLAttributes<HTMLElement>) {
  return <section className={classes("ui-card", className)} {...props} />;
}
export function CardHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={classes("ui-card-header", className)} {...props} />;
}
export function CardContent({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={classes("ui-card-content", className)} {...props} />;
}

export function Badge({ className, ...props }: React.HTMLAttributes<HTMLSpanElement>) {
  return <span className={classes("ui-badge", className)} {...props} />;
}

type AlertProps = React.HTMLAttributes<HTMLDivElement> & { variant?: "default" | "warning" | "destructive" };
export function Alert({ className, variant = "default", role = "status", ...props }: AlertProps) {
  return <div className={classes("ui-alert", `ui-alert-${variant}`, className)} role={role} {...props} />;
}

export function Table({ className, ...props }: React.TableHTMLAttributes<HTMLTableElement>) {
  return <div className="ui-table-wrap"><table className={classes("ui-table", className)} {...props} /></div>;
}
