import Link from "next/link";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { registerAction } from "@/lib/auth-actions";

const ERROR_MESSAGES: Record<string, string> = {
  invalid: "Check your details and try again. Passwords need to be at least 12 characters.",
  unavailable: "Registration is unavailable right now. Please try again soon.",
};

export default async function RegisterPage({ searchParams }: PageProps<"/register">) {
  const params = await searchParams;
  const error = firstValue(params.error);

  return (
    <main className="mx-auto w-full max-w-sm flex-1 space-y-6 px-4 py-10">
      <h1 className="text-2xl font-bold">Create an account</h1>
      <p className="text-sm text-muted-foreground">
        An account lets you watch a medicine name and get an email when it appears in a new alert.
      </p>

      {error && <p role="status">{ERROR_MESSAGES[error] ?? ERROR_MESSAGES.invalid}</p>}

      <form action={registerAction} className="space-y-4">
        <div className="space-y-1">
          <label htmlFor="email" className="text-sm font-medium">
            Email
          </label>
          <Input
            id="email"
            name="email"
            type="email"
            required
            maxLength={254}
            autoComplete="email"
          />
        </div>
        <div className="space-y-1">
          <label htmlFor="password" className="text-sm font-medium">
            Password
          </label>
          <Input
            id="password"
            name="password"
            type="password"
            required
            minLength={12}
            maxLength={200}
            autoComplete="new-password"
          />
          <p className="text-xs text-muted-foreground">At least 12 characters.</p>
        </div>
        <Button type="submit" className="w-full">
          Register
        </Button>
      </form>

      <p className="text-sm text-muted-foreground">
        Already have an account?{" "}
        <Link href="/login" className="text-accent-foreground underline underline-offset-2">
          Log in
        </Link>
      </p>
    </main>
  );
}

function firstValue(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}
