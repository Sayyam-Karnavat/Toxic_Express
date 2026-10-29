import { HandHeart, MessageCircleHeart, ShieldCheck, Sparkles } from "lucide-react";
import { Link } from "react-router-dom";

import { useFeed } from "@/api/feed";
import { PostCard } from "@/components/PostCard";
import { Button } from "@/components/ui/button";

const STEPS = [
  { n: "01", title: "Rant", body: "Pick a category, crank the Frustration Meter, go anonymous if you need to. Let it out." },
  { n: "02", title: "Relate", body: "People who've been there react, share their story, or offer a way out." },
  { n: "03", title: "Resolve", body: "Pin the comment that helped. Your rant becomes a solved story for the next person." },
];

export default function Landing() {
  const trending = useFeed({ sort: "trending" });
  const preview = trending.data?.pages[0]?.items.slice(0, 2) ?? [];

  return (
    <div className="-mt-xl">
      {/* DESIGN.md `hero`: deep-indigo canvas on the animated Blurple -> magenta mesh */}
      <section className="mesh-bg -mx-md rounded-b-[88px] px-md py-section tablet:-mx-xl tablet:px-xl">
        <div className="mx-auto max-w-4xl py-section text-center">
          <p className="mb-md inline-flex items-center gap-xs rounded-pill bg-surface-indigo/70 px-md py-xs text-link-sm">
            <Sparkles className="size-4 text-green" aria-hidden /> The professional network for frustrated people
          </p>
          <h1 className="font-display text-[clamp(40px,8vw,82px)] font-bold uppercase leading-none tracking-tight">
            Scream it out. <span className="block">Get heard.</span>
          </h1>
          <p className="mx-auto mt-xl max-w-2xl text-body-lg text-ink-soft">
            Vent about work, tech, money, landlords and life, find people who get it, and turn
            your worst days into solved stories.
          </p>
          <div className="mt-xxl flex flex-col items-center justify-center gap-sm tablet:flex-row">
            <Button asChild variant="green" size="lg" className="w-full font-display uppercase tablet:w-auto">
              <Link to="/signup">Start ranting</Link>
            </Button>
            <Button asChild variant="white" size="lg" className="w-full tablet:w-auto">
              <Link to="/trending">See what people are yelling about</Link>
            </Button>
          </div>
        </div>
      </section>

      {/* DESIGN.md `marquee-band` */}
      <div className="-mx-md overflow-hidden bg-primary py-lg tablet:-mx-xl" aria-hidden>
        <div className="marquee-track flex w-max gap-xxl whitespace-nowrap font-display text-[clamp(32px,6vw,62px)] font-bold uppercase leading-none">
          {Array.from({ length: 2 }).map((_, i) => (
            <span key={i} className="flex gap-xxl">
              <span>Rant</span><span>·</span><span>Relate</span><span>·</span><span>Resolve</span><span>·</span>
              <span>Rant</span><span>·</span><span>Relate</span><span>·</span><span>Resolve</span><span>·</span>
            </span>
          ))}
        </div>
      </div>

      <section className="mt-section" aria-labelledby="how">
        <h2 id="how" className="font-display text-[clamp(32px,5vw,56px)] font-bold uppercase leading-none">How it works</h2>
        <div className="mt-xl grid gap-md laptop:grid-cols-3">
          {STEPS.map((s) => (
            <div key={s.n} className="gradient-panel rounded-lg p-xl">
              <p className="font-display text-heading-sm font-bold">{s.n}</p>
              <p className="mt-xs font-display text-heading-sm font-bold uppercase">{s.title}</p>
              <p className="mt-xs text-body">{s.body}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="mt-section grid gap-md laptop:grid-cols-3" aria-label="Why Toxic-Express">
        {[
          { Icon: ShieldCheck, title: "Anonymous when you need it", body: "Toggle anonymity per rant. Photos lose their location data. Your boss never finds out." },
          { Icon: HandHeart, title: "Swearing is fine. Harm isn't.", body: "Rant about situations freely. Threats, hate and doxxing are filtered out before they land." },
          { Icon: MessageCircleHeart, title: "Helpers get the credit", body: "Every pinned answer builds your Helper Score and badges. Solving problems is the new flex." },
        ].map(({ Icon, title, body }) => (
          <div key={title} className="rounded-xl bg-surface-indigo p-xxl">
            <Icon className="size-8 text-link-cyan" aria-hidden />
            <p className="mt-md font-display text-heading-sm font-bold">{title}</p>
            <p className="mt-xs text-body text-ink-soft">{body}</p>
          </div>
        ))}
      </section>

      {preview.length > 0 && (
        <section className="mt-section" aria-labelledby="hot">
          <h2 id="hot" className="font-display text-[clamp(32px,5vw,56px)] font-bold uppercase leading-none">Hot right now</h2>
          <div className="mt-xl space-y-md">
            {preview.map((p) => (
              <PostCard key={p.id} post={p} />
            ))}
          </div>
        </section>
      )}

      {/* DESIGN.md `cta-band` */}
      <section className="mt-section rounded-xl bg-primary p-section text-center">
        <p className="font-display text-[clamp(32px,5vw,56px)] font-bold uppercase leading-none">You're not the only one.</p>
        <p className="mx-auto mt-md max-w-[36rem] text-body-lg">Join and find the people who've been exactly where you are.</p>
        <Button asChild variant="green" size="lg" className="mt-xl font-display uppercase">
          <Link to="/signup">Create your account</Link>
        </Button>
      </section>
    </div>
  );
}
