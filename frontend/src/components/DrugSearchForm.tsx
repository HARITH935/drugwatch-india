import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";

// Same plain-GET-form pattern as BatchSearchForm: works with no JavaScript, lands on a
// bookmarkable ?q=... URL.
export function DrugSearchForm({ defaultValue }: { defaultValue?: string }) {
  return (
    <form action="/drugs/search" className="flex flex-wrap gap-2" role="search">
      <label htmlFor="q" className="sr-only">
        Medicine name
      </label>
      <Input
        id="q"
        name="q"
        required
        minLength={3}
        maxLength={120}
        defaultValue={defaultValue}
        placeholder="e.g. Paracetamol"
        className="max-w-sm"
      />
      <Button type="submit">Search</Button>
    </form>
  );
}
