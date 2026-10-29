import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router';
import { Avatar, shownName } from '@/components/Avatar';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Skeleton } from '@/components/ui/skeleton';
import { api } from '@/lib/api';
import { useMe } from '../features/auth/useMe';

/**
 * The signed-in slot of the header (UI-SPEC "Layout and Navigation"): a 44px avatar button that
 * opens the account menu (`Account`, `My trips`, `Sign out`). While `/api/me` resolves the slot is
 * a 32px decorative skeleton circle, so neither `Sign in` nor the avatar flashes. Signed out, or
 * when `/api/me` fails for any reason other than 401, it shows the quiet `Sign in` link: the
 * header never blocks the page.
 */
export function AccountMenu() {
  const me = useMe();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const signOut = useMutation({
    mutationFn: async () => {
      const { response } = await api.POST('/api/auth/signout');
      if (!response.ok) {
        throw new Error(`Sign out failed (${response.status})`);
      }
    },
    onSuccess: () => {
      navigate('/signin');
      queryClient.clear();
    },
  });

  if (me.isPending) {
    return <Skeleton className="size-8 rounded-full" />;
  }
  if (me.isError || me.data === null) {
    return (
      <Link
        to="/signin"
        className="inline-flex h-11 min-w-11 items-center justify-center rounded-lg px-4 text-base font-semibold text-foreground hover:bg-accent"
      >
        Sign in
      </Link>
    );
  }

  const account = me.data;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label="Account menu"
          aria-haspopup="menu"
          className="inline-flex size-11 items-center justify-center rounded-full"
        >
          <Avatar
            name={shownName(account)}
            kind={account.avatar_kind}
            avatarKey={account.avatar_key}
            size={32}
          />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem asChild>
          <Link to="/account">Account</Link>
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <Link to="/">My trips</Link>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          disabled={signOut.isPending}
          onSelect={() => signOut.mutate()}
        >
          Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
