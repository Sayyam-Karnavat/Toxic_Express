import { useMeta } from "@/api/meta";
import { Card } from "@/components/ui/card";

const RULES = [
  ["Rant about situations, not people.", "Name the problem, not the person. No full names, photos or details that identify someone."],
  ["No personal info.", "Phone numbers, emails, addresses and IDs get blocked automatically, including your own."],
  ["Swearing is fine. Threats aren't.", "Anger is welcome. Threats, hate speech and harassment get removed and can lead to strikes."],
  ["Anonymous isn't untraceable.", "Anonymous rants hide you from other users, but moderators can see who posted to keep people safe."],
  ["Three strikes.", "Three active strikes means a 7-day suspension. Every decision can be appealed once."],
];

export default function HelpPage() {
  const { data } = useMeta();
  return (
    <div className="space-y-xl">
      <section>
        <h1 className="font-display text-heading-lg font-bold uppercase leading-none">Help & safety</h1>
        <p className="mt-sm max-w-2xl text-body text-ink-soft">Toxic-Express is for letting it out and getting through it. Here's how we keep it a place you want to be.</p>
      </section>
      {/* Calm treatment on purpose: no caps, no gradients. */}
      <section aria-labelledby="crisis" className="rounded-lg border border-indigo-line bg-canvas p-xl">
        <h2 id="crisis" className="text-heading-sm font-semibold">If you're struggling right now</h2>
        <p className="mt-xs text-body text-ink-soft">You deserve support from a real person. These services are free and confidential.</p>
        <ul className="mt-md space-y-sm">
          {data?.crisis_resources.map((r) => (
            <li key={r.name} className="text-body">
              <span className="text-ink-soft">{r.region}:</span>{" "}
              <a href={r.url} target="_blank" rel="noreferrer" className="text-link-cyan underline">{r.name}</a>
              {r.phone && <> · call or text <strong>{r.phone}</strong></>}
            </li>
          ))}
        </ul>
        <p className="mt-md text-link-sm text-ink-faint">If you or someone else is in immediate danger, contact your local emergency number.</p>
      </section>
      <section id="rules" aria-labelledby="rules-h">
        <h2 id="rules-h" className="font-display text-heading-sm font-bold uppercase">Community rules</h2>
        <div className="mt-md grid gap-md tablet:grid-cols-2">
          {RULES.map(([title, body]) => (
            <Card key={title}>
              <p className="font-display text-link-lg font-bold">{title}</p>
              <p className="mt-xs text-body text-ink-soft">{body}</p>
            </Card>
          ))}
        </div>
      </section>
    </div>
  );
}
