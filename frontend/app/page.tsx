import Link from "next/link";

export default function HomePage() {
  return (
    <section className="relative overflow-hidden rounded-3xl min-h-[70vh] bg-[linear-gradient(135deg,#1a2332_0%,#2f6f5e_55%,#c45c26_100%)] text-white">
      <div className="absolute inset-0 opacity-30 bg-[url('data:image/svg+xml,%3Csvg width=%2760%27 height=%2760%27 viewBox=%270 0 60 60%27 xmlns=%27http://www.w3.org/2000/svg%27%3E%3Cg fill=%27none%27 fill-rule=%27evenodd%27%3E%3Cg fill=%27%23ffffff%27 fill-opacity=%270.15%27%3E%3Cpath d=%27M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z%27/%3E%3C/g%3E%3C/g%3E%3C/svg%3E')]" />
      <div className="relative z-10 px-8 py-16 md:px-14 md:py-24 max-w-2xl">
        <p className="font-display text-4xl md:text-6xl leading-tight mb-4">FacadePlan</p>
        <h1 className="text-xl md:text-2xl font-semibold mb-4 text-white/95">
          See your house renovated before you spend.
        </h1>
        <p className="text-white/80 mb-8 text-lg">
          Upload an exterior photo, apply materials, generate a redesign, and get transparent
          quantity and cost estimates — ready to discuss with contractors.
        </p>
        <div className="flex flex-wrap gap-3">
          <Link href="/register" className="btn bg-white text-ink hover:bg-sand">
            Start planning
          </Link>
          <Link href="/login" className="btn border border-white/40 text-white hover:bg-white/10">
            Log in
          </Link>
        </div>
      </div>
    </section>
  );
}
