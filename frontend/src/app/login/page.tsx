import Link from "next/link";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { loginAction } from "@/lib/auth-actions";

const ERROR_MESSAGES: Record<string, string> = {
  // The exact wording AuthController returns for both a wrong password and an unknown email -
  // repeated here rather than reworded, so the two paths stay indistinguishable end to end.
  invalid: "Email or password is not correct.",
  unavailable: "Login is unavailable right now. Please try again soon.",
};

export default async function LoginPage({ searchParams }: PageProps<"/login">) {
  const params = await searchParams;
  const error = firstValue(params.error);

  return (
    <main className="mx-auto w-full max-w-sm flex-1 space-y-6 px-4 py-10">
      <h1 className="text-2xl font-bold">Log in</h1>

      {error && <p role="status">{ERROR_MESSAGES[error] ?? ERROR_MESSAGES.invalid}</p>}

      <form action={loginAction} className="space-y-4">
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
            maxLength={200}
            autoComplete="current-password"
          />
        </div>
        <Button type="submit" className="w-full">
          Log in
        </Button>
      </form>

      <p className="text-sm text-muted-foreground">
        No account yet?{" "}
        <Link href="/register" className="text-accent-foreground underline underline-offset-2">
          Register
        </Link>
      </p>
    </main>
  );
}

function firstValue(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}
