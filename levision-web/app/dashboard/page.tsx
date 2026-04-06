import { redirect } from 'next/navigation'
import { createClient } from '@/lib/supabase/server'
import { normalizeUserRole, type Profile } from '@/lib/types'
import { getDevBypassProfile, hasDevBypassSession } from '@/lib/dev-bypass'
import PageShell from '@/components/PageShell'
import RoleSwitcher from '@/components/RoleSwitcher'
import { UserRoleProvider } from '@/components/UserRoleProvider'
import { signOut } from './actions'
import DashboardTabs from './DashboardTabs'
import Image from 'next/image'
import Link from 'next/link'

export default async function DashboardPage() {
  const isDevBypass = await hasDevBypassSession()
  const supabase = await createClient()

  const {
    data: { user },
  } = await supabase.auth.getUser()

  if (!user && !isDevBypass) {
    redirect('/login')
  }

  let profile: Profile | null = null

  if (user) {
    const { data } = await supabase
      .from('profiles')
      .select('*')
      .eq('id', user.id)
      .single<Profile>()

    profile = data
  } else if (isDevBypass) {
    profile = getDevBypassProfile()
  }

  if (!profile || !profile.onboarding_complete) {
    redirect('/onboarding')
  }

  return (
    <PageShell>
      <UserRoleProvider
        userId={profile.id}
        initialRole={normalizeUserRole(profile.role)}
      >
      <div className="min-h-screen flex flex-col">

        {/* Navbar */}
        <nav className="flex items-center justify-between px-8 py-5 border-b border-[rgba(200,136,58,0.15)] bg-pitch/80 backdrop-blur-sm relative z-10">
          {/* Logo */}
          <Link
            href="/dashboard"
            className="flex items-center gap-2.5 text-offwhite hover:opacity-90 transition-opacity cursor-pointer"
          >
            <Image src="/bron-face.png" alt="LeVision" width={32} height={32} className="object-contain" />
            <span className="font-display text-[1.7rem] tracking-[0.06em] leading-none">
              Le<span className="text-brand">Vision</span>
            </span>
          </Link>

          {/* Right side */}
          <div className="flex items-center gap-5">
            <RoleSwitcher disabled={isDevBypass} />
            <span className="text-[0.78rem] text-muted font-light tracking-[0.04em] hidden sm:block">
              {profile.email}
            </span>
            <form action={signOut}>
              <button
                type="submit"
                className="text-muted hover:text-offwhite font-body text-[0.73rem] tracking-[0.06em] bg-transparent border-none transition-colors duration-200 cursor-pointer"
              >
                Sign out
              </button>
            </form>
          </div>
        </nav>

        {/* Tabs */}
        <DashboardTabs />

      </div>
      </UserRoleProvider>
    </PageShell>
  )
}
