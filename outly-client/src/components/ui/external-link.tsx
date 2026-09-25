import { Link002 } from "@/components/ui/skiper-ui/skiper40";
import { cn } from "@/lib/utils";

export function ExternalLink({
  href,
  children,
  className,
}: {
  href: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <Link002
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className={cn("text-sm", className)}
    >
      {children}
    </Link002>
  );
}
