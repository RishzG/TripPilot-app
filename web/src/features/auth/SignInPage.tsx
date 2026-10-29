import { useQuery } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router';
import { api, unwrap } from '../../lib/api';
import { JUDGE_LOGINS } from './judgeLogins';
import { safeNextPath } from './useMe';

const BUTTON_CLASS =
  'inline-flex min-h-11 w-full items-center justify-center rounded-lg bg-accent px-4 text-base font-semibold text-accent-foreground';
const OUTLINE_CLASS =
  'inline-flex min-h-11 w-full items-center justify-center rounded-lg border border-border px-4 text-base font-semibold';

const RETURN_ERRORS: Record<string, string> = {
  cancelled: "You cancelled at PayPal. Log in again when you're ready.",
  failed: "Couldn't log you in with PayPal. Try again.",
};

function CopyRow({
  label,
  value,
  copyLabel,
}: {
  label: string;
  value: string;
  copyLabel: string;
}) {
  return (
    <div className="flex flex-col gap-2">
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="break-all text-base">{value}</dd>
      <button
        type="button"
        onClick={() => void navigator.clipboard.writeText(value)}
        className={OUTLINE_CLASS}
      >
        {copyLabel}
      </button>
    </div>
  );
}

/** Sign in with a real PayPal sandbox account (ACC-02), the demo, or a published judge login. */
export function SignInPage() {
  const [searchParams] = useSearchParams();
  const next = safeNextPath(searchParams.get('next'), '');
  const returnError = RETURN_ERRORS[searchParams.get('error') ?? ''];
  const demo = useQuery({
    queryKey: ['demo-personas'],
    queryFn: async () => unwrap(await api.GET('/api/demo/personas')),
    retry: false,
  });
  const demoAvailable = demo.isSuccess && demo.data.length > 0;
  const suffix = next === '' ? '' : `?next=${encodeURIComponent(next)}`;

  return (
    <div className="mx-auto w-full max-w-md p-4 pt-6">
      <h1 className="text-balance break-words text-[1.75rem] font-semibold leading-[1.2]">
        Sign in to TripPilot
      </h1>
      <p className="mt-2 text-base">
        We'll use your PayPal name and email to set you up. Nothing is charged.
      </p>
      {returnError !== undefined && (
        <p role="alert" className="mt-4 text-sm text-destructive">
          {returnError}
        </p>
      )}
      <div className="mt-6 flex flex-col gap-2">
        <a href={`/api/auth/paypal/start${suffix}`} className={BUTTON_CLASS}>
          Log in with PayPal
        </a>
        {demoAvailable && (
          <Link to={`/demo${suffix}`} className={OUTLINE_CLASS}>
            Try the demo
          </Link>
        )}
      </div>
      {JUDGE_LOGINS.length > 0 && (
        <section aria-labelledby="judge-logins" className="mt-8">
          <h2 id="judge-logins" className="text-xl font-semibold leading-[1.2]">
            Judge sandbox logins
          </h2>
          <p className="mt-2 text-base">
            Sandbox PayPal accounts for trying the real log-in. No real money is
            involved.
          </p>
          <ul className="mt-4 flex flex-col gap-6">
            {JUDGE_LOGINS.map((login) => (
              <li key={login.email}>
                <dl className="flex flex-col gap-4">
                  <CopyRow
                    label="Email"
                    value={login.email}
                    copyLabel="Copy email"
                  />
                  <CopyRow
                    label="Password"
                    value={login.password}
                    copyLabel="Copy password"
                  />
                </dl>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
