import Link from "next/link";
import { Icon, IconName } from "@/components/icons";

const STEPS: { icon: IconName; title: string; body: string }[] = [
  { icon: "upload", title: "Upload a photo", body: "Snap a clear daytime photo of your facade. Automatic quality checks tell you if it's usable." },
  { icon: "layers", title: "Review regions", body: "AI detects walls, windows, balconies and more. Adjust any outline in a couple of clicks." },
  { icon: "palette", title: "Apply materials", body: "Pick paint, cladding, tiles or railings per region and compare design variants." },
  { icon: "sparkles", title: "See the redesign", body: "Generate a before/after visualization so you know what you're paying for." },
  { icon: "calculator", title: "Estimate costs", body: "Transparent area, quantity, material and labor totals — editable by your professionals." },
  { icon: "file", title: "Share a report", body: "Download a branded PDF with images and a full breakdown for contractor discussions." },
];

const AUDIENCES = [
  { title: "Homeowners", body: "Visualize options and understand costs before talking to contractors." },
  { title: "Contractors & builders", body: "Adjust quantities and rates, then hand clients a clear quotation basis." },
  { title: "Architects & consultants", body: "Collaborate on shared projects and brand reports with your logo." },
  { title: "Material suppliers", body: "List materials with rates, coverage and wastage so they appear in designs." },
];

export default function HomePage() {
  return (
    <div className="space-y-16 sm:space-y-24">
      <section className="relative overflow-hidden rounded-3xl bg-slate-900 text-white">
        <div
          aria-hidden="true"
          className="absolute inset-0 bg-[radial-gradient(ellipse_at_top_left,rgba(79,156,135,0.45),transparent_55%),radial-gradient(ellipse_at_bottom_right,rgba(208,106,51,0.35),transparent_50%)]"
        />
        <div
          aria-hidden="true"
          className="absolute inset-0 opacity-[0.07] [background-image:linear-gradient(to_right,#fff_1px,transparent_1px),linear-gradient(to_bottom,#fff_1px,transparent_1px)] [background-size:40px_40px]"
        />
        <div className="relative z-10 grid gap-10 px-6 py-14 sm:px-12 sm:py-20 lg:grid-cols-[1.2fr_1fr] lg:items-center">
          <div>
            <span className="inline-flex items-center gap-2 rounded-full bg-white/10 px-3 py-1 text-xs font-medium text-white/90 ring-1 ring-inset ring-white/20">
              <Icon name="sparkles" className="h-3.5 w-3.5" /> AI-assisted exterior renovation planning
            </span>
            <h1 className="mt-5 font-display text-4xl font-semibold leading-[1.1] sm:text-5xl lg:text-6xl">
              See your house renovated before you spend.
            </h1>
            <p className="mt-5 max-w-xl text-base text-white/75 sm:text-lg">
              Upload an exterior photo, apply materials, generate a redesign, and get transparent quantity and cost
              estimates — ready to discuss with contractors.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link href="/register" className="btn btn-lg bg-white text-slate-900 shadow-sm hover:bg-slate-100">
                Start planning <Icon name="arrowRight" />
              </Link>
              <Link href="/login" className="btn btn-lg text-white ring-1 ring-inset ring-white/30 hover:bg-white/10">
                Log in
              </Link>
            </div>
          </div>
          <div className="hidden lg:block">
            <div className="rounded-2xl bg-white/5 p-5 ring-1 ring-inset ring-white/15 backdrop-blur">
              <div className="flex items-center justify-between text-xs text-white/60">
                <span>Estimate summary</span>
                <span className="rounded-full bg-emerald-400/15 px-2 py-0.5 text-emerald-300">Estimated</span>
              </div>
              <div className="mt-4 space-y-3">
                {[
                  ["Main wall · Texture paint", "₹ 48,600"],
                  ["Balcony · Stone cladding", "₹ 31,250"],
                  ["Railing · Glass", "₹ 22,900"],
                ].map(([k, v]) => (
                  <div key={k} className="flex items-center justify-between rounded-lg bg-white/5 px-3 py-2.5 text-sm">
                    <span className="text-white/80">{k}</span>
                    <span className="font-semibold tabular-nums">{v}</span>
                  </div>
                ))}
              </div>
              <div className="mt-4 flex items-center justify-between border-t border-white/10 pt-4">
                <span className="text-sm text-white/70">Grand total</span>
                <span className="text-2xl font-bold tabular-nums">₹ 1,02,750</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section aria-labelledby="how-heading">
        <div className="max-w-2xl">
          <p className="text-sm font-semibold uppercase tracking-wide text-brand-600">How it works</p>
          <h2 id="how-heading" className="mt-2 text-2xl font-bold text-slate-900 sm:text-3xl">
            From photo to quotation in six guided steps
          </h2>
        </div>
        <ol className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {STEPS.map((s, i) => (
            <li key={s.title} className="card-panel p-6">
              <div className="flex items-center gap-3">
                <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-50 text-brand-600">
                  <Icon name={s.icon} className="h-5 w-5" />
                </span>
                <span className="text-xs font-semibold text-slate-400">Step {i + 1}</span>
              </div>
              <h3 className="mt-4 font-semibold text-slate-900">{s.title}</h3>
              <p className="mt-1.5 text-sm leading-relaxed text-slate-600">{s.body}</p>
            </li>
          ))}
        </ol>
      </section>

      <section aria-labelledby="who-heading" className="card-panel overflow-hidden">
        <div className="grid lg:grid-cols-[1fr_2fr]">
          <div className="bg-brand-50 p-8 sm:p-10">
            <h2 id="who-heading" className="text-2xl font-bold text-slate-900">
              Built for everyone on the project
            </h2>
            <p className="mt-2 text-sm text-slate-600">
              Role-aware workspaces let each person contribute what they know — and nothing they shouldn&apos;t change.
            </p>
            <Link href="/register" className="btn-primary mt-6">
              Create a free account
            </Link>
          </div>
          <div className="grid gap-px bg-slate-100 sm:grid-cols-2">
            {AUDIENCES.map((a) => (
              <div key={a.title} className="bg-white p-6">
                <div className="flex items-center gap-2 font-semibold text-slate-900">
                  <Icon name="check" className="h-4 w-4 text-brand-600" />
                  {a.title}
                </div>
                <p className="mt-1.5 text-sm text-slate-600">{a.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
