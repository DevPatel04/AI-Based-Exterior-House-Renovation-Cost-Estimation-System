import Link from "next/link";
import { ReactNode } from "react";
import { Icon } from "@/components/icons";

export default function AuthCard({
  title,
  subtitle,
  children,
  footer,
  wide,
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
  footer: ReactNode;
  wide?: boolean;
}) {
  return (
    <div className={`mx-auto w-full ${wide ? "max-w-2xl" : "max-w-md"} py-4 sm:py-8`}>
      <div className="mb-6 text-center">
        <Link href="/" className="inline-flex h-11 w-11 items-center justify-center rounded-xl bg-brand-600 text-white shadow-sm" aria-label="FacadePlan home">
          <Icon name="home" className="h-5 w-5" />
        </Link>
        <h1 className="mt-4 text-2xl font-bold text-slate-900 sm:text-3xl">{title}</h1>
        <p className="mt-1.5 text-sm text-slate-600">{subtitle}</p>
      </div>
      <div className="card-panel p-6 sm:p-8">{children}</div>
      <p className="mt-6 text-center text-sm text-slate-600">{footer}</p>
    </div>
  );
}
