/**
 * Published sandbox PayPal logins that judges may use to try the real Log in with PayPal (D-16).
 * Plan 01-17 fills the list once the sandbox buyer accounts exist; while it is empty the sign-in
 * page shows no judge block. These are sandbox accounts with no real money, never real credentials.
 */
export interface JudgeLogin {
  email: string;
  password: string;
}

export const JUDGE_LOGINS: JudgeLogin[] = [];
