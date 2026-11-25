import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";

// A living reference for the tokens and components defined in globals.css / src/components/ui.
// Not linked from anywhere a visitor would find it - it exists so a later step (or a future
// reviewer) can see every token and component in one place rather than hunting through pages.
export default function StyleGuidePage() {
  return (
    <main className="mx-auto w-full max-w-3xl flex-1 space-y-12 px-4 py-10">
      <header className="space-y-2">
        <h1 className="text-3xl font-bold">Design system</h1>
        <p className="text-muted-foreground">
          Phase 11 step 1. Tokens in <code>globals.css</code>, components in{" "}
          <code>src/components/ui</code>.
        </p>
      </header>

      <Section title="Colour">
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Swatch
            name="background"
            className="bg-background text-foreground border border-border"
          />
          <Swatch name="card" className="bg-card text-card-foreground border border-border" />
          <Swatch name="primary" className="bg-primary text-primary-foreground" />
          <Swatch
            name="muted-foreground"
            className="bg-background text-muted-foreground border border-border"
          />
        </div>
      </Section>

      <Section title="Status — flagged vs. not found (never red/green)">
        <p className="text-sm text-muted-foreground">
          Deliberately the same slate hue as ordinary UI chrome, not a reassuring green — a
          &ldquo;not found&rdquo; result must never read as &ldquo;safe&rdquo; (CLAUDE.md §6).
        </p>
        <div className="flex flex-wrap gap-3">
          <Badge variant="flagged">Reported in a CDSCO alert</Badge>
          <Badge variant="notFound">No matching alert found</Badge>
          <Badge variant="error">Request failed</Badge>
          <Badge variant="neutral">Neutral</Badge>
        </div>
      </Section>

      <Section title="Typography">
        <div className="space-y-2">
          <p className="text-3xl font-bold">Heading / 3xl bold</p>
          <p className="text-xl font-semibold">Heading / xl semibold</p>
          <p className="text-base">Body / base</p>
          <p className="text-sm text-muted-foreground">Caption / sm muted</p>
        </div>
      </Section>

      <Section title="Button">
        <div className="flex flex-wrap items-center gap-3">
          <Button>Primary</Button>
          <Button variant="secondary">Secondary</Button>
          <Button variant="outline">Outline</Button>
          <Button variant="ghost">Ghost</Button>
          <Button disabled>Disabled</Button>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Button size="sm">Small</Button>
          <Button size="default">Default</Button>
          <Button size="lg">Large</Button>
        </div>
      </Section>

      <Section title="Input">
        <Input placeholder="Batch number or drug name" className="max-w-sm" />
      </Section>

      <Section title="Card">
        <Card>
          <p className="font-semibold">Card title</p>
          <p className="text-sm text-muted-foreground">Card body text inside the default card.</p>
        </Card>
      </Section>
    </main>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-4">
      <h2 className="text-xl font-semibold">{title}</h2>
      {children}
    </section>
  );
}

function Swatch({ name, className }: { name: string; className: string }) {
  return (
    <div
      className={`flex h-20 items-end rounded-(--radius-md) p-2 text-xs font-medium ${className}`}
    >
      {name}
    </div>
  );
}
