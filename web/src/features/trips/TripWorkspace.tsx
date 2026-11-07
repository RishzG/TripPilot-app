import {
  ArrowLeft,
  CalendarDays,
  ChevronRight,
  Compass,
  CreditCard,
  LayoutDashboard,
  Map as MapIcon,
  MessageCircle,
  Settings2,
  Sparkles,
  Users,
  Wallet,
} from 'lucide-react';
import { type ReactNode, useEffect, useRef } from 'react';
import { Link } from 'react-router';
import { AccountMenu } from '@/app/AccountMenu';
import { Avatar, shownName } from '@/components/Avatar';
import { Logo } from '@/components/Logo';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import type { components } from '@/lib/api-types';
import { cn } from '@/lib/utils';
import { useMe } from '../auth/useMe';

export const WORKSPACE_VIEWS = [
  'chat',
  'plan',
  'bookings',
  'trip',
  'splits',
  'preferences',
  'group',
] as const;
export type WorkspaceView = (typeof WORKSPACE_VIEWS)[number];
type Trip = components['schemas']['TripView'];

const NAVIGATION = [
  { view: 'chat', label: 'Chat', icon: MessageCircle },
  { view: 'plan', label: 'Plan', icon: MapIcon },
  { view: 'bookings', label: 'Bookings', icon: CreditCard, soon: true },
  { view: 'trip', label: 'Trip overview', icon: LayoutDashboard },
  { view: 'splits', label: 'Splits', icon: Wallet, soon: true },
  { view: 'preferences', label: 'Preferences', icon: Settings2 },
  { view: 'group', label: 'Group', icon: Users },
] as const;

export function TripWorkspace({
  trip,
  view,
  onNavigate,
  children,
}: {
  trip: Trip;
  view: WorkspaceView;
  onNavigate: (view: WorkspaceView) => void;
  children: ReactNode;
}) {
  const me = useMe();
  const content = useRef<HTMLDivElement>(null);
  const previousView = useRef(view);
  useEffect(() => {
    if (previousView.current === view) return;
    content.current?.scrollTo?.({ top: 0 });
    previousView.current = view;
  }, [view]);
  const active = NAVIGATION.find((item) => item.view === view);
  return (
    <div className="grid min-h-[calc(100dvh-1.75rem)] md:h-[calc(100dvh-1.75rem)] md:min-h-0 md:grid-cols-[208px_minmax(0,1fr)]">
      <aside
        className="flex flex-col border-b border-border bg-background md:min-h-0 md:border-r md:border-b-0"
        aria-label="Trip workspace sidebar"
      >
        <div className="flex h-24 shrink-0 items-center px-6">
          <Logo />
        </div>
        <nav
          aria-label="Trip workspace"
          className="flex flex-wrap gap-1 px-3 md:flex-col md:overflow-y-auto"
        >
          {NAVIGATION.map((item, index) => (
            <button
              key={item.view}
              type="button"
              aria-current={view === item.view ? 'page' : undefined}
              onClick={() => onNavigate(item.view)}
              className={cn(
                'flex min-h-12 items-center gap-3 rounded-xl px-4 text-left text-sm font-medium transition-colors hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring',
                index === 5 && 'md:mt-6',
                view === item.view &&
                  'bg-primary/10 font-semibold text-primary-hover',
              )}
            >
              <item.icon size={19} aria-hidden="true" />
              <span>{item.label}</span>
              {'soon' in item && item.soon && (
                <span className="ml-auto rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                  Soon
                </span>
              )}
            </button>
          ))}
        </nav>
        <div className="mt-auto flex flex-col gap-2 px-5 py-6 text-sm">
          <Link
            to="/"
            className="flex min-h-10 items-center gap-2 rounded-lg px-2 hover:bg-muted"
          >
            <ArrowLeft size={16} aria-hidden="true" /> All trips
          </Link>
          <Link
            to="/account"
            className="flex min-h-10 items-center gap-2 rounded-lg px-2 hover:bg-muted"
          >
            <Settings2 size={16} aria-hidden="true" /> Account
          </Link>
          {me.data?.is_persona && (
            <Link
              to="/demo"
              className="mt-2 rounded-lg border border-border px-3 py-2.5 text-center text-xs font-semibold hover:bg-muted"
            >
              Switch demo persona
            </Link>
          )}
        </div>
      </aside>
      <div className="flex min-w-0 flex-col md:min-h-0">
        <header className="flex shrink-0 flex-wrap items-center justify-between gap-4 border-b border-border bg-background px-6 py-5 lg:px-8">
          <div className="min-w-0">
            <p className="mb-1 flex items-center gap-1.5 text-[11px] font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              Your trip workspace <ChevronRight size={12} aria-hidden="true" />{' '}
              {active?.label}
            </p>
            <h1
              title={trip.name}
              className="max-w-[38rem] truncate text-2xl font-semibold tracking-tight xl:text-3xl"
            >
              {trip.name}
            </h1>
          </div>
          <div className="flex shrink-0 items-center gap-3">
            <div className="flex items-center gap-3 p-1.5">
              <div className="flex -space-x-2" aria-hidden="true">
                {trip.members.slice(0, 4).map((member) => (
                  <span
                    key={member.account_id}
                    className="rounded-full ring-2 ring-background"
                    title={shownName(member)}
                  >
                    <Avatar
                      name={shownName(member)}
                      kind={member.avatar_kind}
                      avatarKey={member.avatar_key}
                      size={32}
                    />
                  </span>
                ))}
              </div>
              <span className="text-sm text-muted-foreground">
                {trip.members.length} of 12 in
              </span>
            </div>
            <div className="h-8 border-l border-border" />
            <AccountMenu />
          </div>
        </header>
        <div className="flex items-center justify-between gap-3 border-b border-border bg-card/50 px-6 py-2.5 text-xs lg:px-8">
          <span className="flex items-center gap-2 text-muted-foreground">
            <span className="size-1.5 rounded-full bg-primary" /> Planning
            together
          </span>
          <div className="flex items-center gap-3">
            <Badge className="bg-muted font-normal text-muted-foreground">
              No plan selected
            </Badge>
            {me.data?.is_persona && (
              <span className="text-muted-foreground">Demo persona</span>
            )}
          </div>
        </div>
        <div
          className="min-h-0 flex-1 overflow-y-auto p-5 lg:p-6 xl:p-8"
          data-testid="workspace-content"
          ref={content}
        >
          {children}
        </div>
      </div>
    </div>
  );
}

export function EmptyPlan({
  onNavigate,
}: {
  onNavigate: (view: WorkspaceView) => void;
}) {
  return (
    <section
      aria-labelledby="empty-plan-title"
      className="flex h-full min-h-96 min-w-0 flex-col overflow-hidden rounded-2xl border border-border bg-card"
    >
      <div className="flex items-center justify-between border-b border-border px-6 py-4">
        <span className="flex items-center gap-2 text-sm font-semibold">
          <CalendarDays size={18} aria-hidden="true" /> Itinerary
        </span>
        <span className="text-xs text-muted-foreground">No itinerary yet</span>
      </div>
      <div className="flex min-h-0 flex-1 flex-col items-center justify-center px-7 py-4 text-center 2xl:px-14 2xl:py-8">
        <div className="relative mb-3 flex size-14 shrink-0 items-center justify-center rounded-full border border-dashed border-primary/30 bg-primary/5">
          <Compass
            size={28}
            strokeWidth={1.25}
            className="text-primary"
            aria-hidden="true"
          />
          <span className="absolute -right-1 bottom-2 flex size-7 items-center justify-center rounded-full border border-border bg-card">
            <Sparkles size={13} className="text-primary" aria-hidden="true" />
          </span>
        </div>
        <p className="text-[10px] font-semibold tracking-[0.18em] text-primary uppercase">
          Room for a great trip
        </p>
        <h2
          id="empty-plan-title"
          className="mt-2 max-w-sm text-2xl font-semibold leading-tight tracking-tight 2xl:text-3xl"
        >
          Your next adventure starts with a conversation.
        </h2>
        <p className="mt-3 max-w-sm text-sm leading-relaxed text-muted-foreground">
          Share your ideas in chat and add what matters to you. The organiser
          can save an itinerary draft for the group.
        </p>
        <div className="mt-5 flex shrink-0 flex-wrap justify-center gap-3">
          <Button type="button" onClick={() => onNavigate('chat')}>
            Open group chat
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={() => onNavigate('preferences')}
          >
            Add your preferences
          </Button>
        </div>
      </div>
      <div className="mx-6 mb-4 shrink-0 rounded-xl bg-muted/60 px-4 py-3 text-[11px] leading-relaxed text-muted-foreground">
        <p>Your plan will appear here once the group starts planning</p>
        <div className="mt-1 flex flex-wrap justify-between gap-1">
          <span>Drafts include estimated costs.</span>
          <span>Nobody pays anything yet.</span>
        </div>
      </div>
    </section>
  );
}

export function UpcomingView({ kind }: { kind: 'bookings' | 'splits' }) {
  const bookings = kind === 'bookings';
  const Icon = bookings ? CreditCard : Wallet;
  return (
    <section className="mx-auto flex min-h-[28rem] max-w-3xl flex-col items-center justify-center rounded-2xl border border-border bg-card p-10 text-center">
      <span className="mb-5 flex size-16 items-center justify-center rounded-2xl bg-muted">
        <Icon size={28} className="text-primary" aria-hidden="true" />
      </span>
      <Badge>Coming later</Badge>
      <h2 className="mt-4 text-2xl font-semibold">
        {bookings ? 'A place for every booking' : 'Keep the costs clear'}
      </h2>
      <p className="mt-3 max-w-md text-sm leading-relaxed text-muted-foreground">
        {bookings
          ? 'Your booking tasks, provider links and confirmations will live here. Booking tools are not available yet.'
          : 'Shared expenses, individual shares and settlements will live here. Expense and payment tools are not available yet.'}
      </p>
    </section>
  );
}
