/** The "you can't join" copy, shared by the join page and the post-login /join-failed page. */
export interface JoinNotice {
  heading: string;
  body: string;
}

export const REFUSALS: Record<string, JoinNotice> = {
  removed: {
    heading: "You can't join this trip",
    body: 'The organiser removed you from this trip. Ask them to add you back.',
  },
  full: {
    heading: 'This trip is full',
    body: 'It already has 12 people.',
  },
  closed: {
    heading: 'Joining is closed',
    body: 'Ask the organiser to open it again.',
  },
};

export const BAD_LINK: JoinNotice = {
  heading: "This invite link isn't working",
  body: 'It may have been reset. Ask the organiser for a new one.',
};

/** The notice for a refusal reason; any other reason (not_found, unknown) is a bad link. */
export function noticeForReason(reason: string | null): JoinNotice {
  return (reason !== null ? REFUSALS[reason] : undefined) ?? BAD_LINK;
}

export function Notice({ heading, body }: JoinNotice) {
  return (
    <div className="mx-auto w-full max-w-md p-4 pt-6">
      <h1 className="text-xl font-semibold leading-[1.2]">{heading}</h1>
      <p className="mt-2 text-muted-foreground">{body}</p>
    </div>
  );
}
