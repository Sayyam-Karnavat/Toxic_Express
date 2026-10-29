import { lazy, Suspense, type ReactNode } from "react";
import { createBrowserRouter, Navigate } from "react-router-dom";

import { AppShell, BareLayout } from "./components/AppShell";
import { GuestOnly, RequireAuth, RequireMod } from "./components/guards";
import { PageSpinner } from "./components/ui/spinner";
import {
  AuthCallbackPage,
  ForgotPasswordPage,
  LoginPage,
  OnboardingPage,
  ResetPasswordPage,
  SignupPage,
  VerifyEmailPage,
} from "./pages/AuthPages";
import { CategoryPage, HomePage, SortedFeedPage, TagPage } from "./pages/Feed";
import NotFound from "./pages/NotFound";
import PostDetail from "./pages/PostDetail";

// Less-visited areas are code-split.
const ProfilePage = lazy(() => import("./pages/Profile"));
const SearchPage = lazy(() => import("./pages/Search"));
const NotificationsPage = lazy(() => import("./pages/Notifications"));
const HelpPage = lazy(() => import("./pages/Help"));
const ModQueuePage = lazy(() => import("./pages/ModQueue"));
const SettingsLayout = lazy(() => import("./pages/settings/SettingsLayout"));
const ProfileSettings = lazy(() => import("./pages/settings/ProfileSettings"));
const AccountSettings = lazy(() => import("./pages/settings/AccountSettings"));
const ModerationHistory = lazy(() => import("./pages/settings/ModerationHistory"));
const Prefs = {
  Privacy: lazy(() => import("./pages/settings/PreferenceSettings").then((m) => ({ default: m.PrivacySettings }))),
  Content: lazy(() => import("./pages/settings/PreferenceSettings").then((m) => ({ default: m.ContentSettings }))),
  Notifications: lazy(() => import("./pages/settings/PreferenceSettings").then((m) => ({ default: m.NotificationSettings }))),
  Blocked: lazy(() => import("./pages/settings/PreferenceSettings").then((m) => ({ default: m.BlockedSettings }))),
};

const lazyEl = (node: ReactNode) => <Suspense fallback={<PageSpinner />}>{node}</Suspense>;
const authed = (node: ReactNode) => <RequireAuth>{lazyEl(node)}</RequireAuth>;
const guest = (node: ReactNode) => <GuestOnly>{node}</GuestOnly>;

export const router = createBrowserRouter([
  {
    element: <AppShell />,
    children: [
      { path: "/", element: <HomePage /> },
      { path: "/latest", element: <SortedFeedPage sort="latest" /> },
      { path: "/trending", element: <SortedFeedPage sort="trending" /> },
      { path: "/solved", element: <SortedFeedPage sort="solved" /> },
      { path: "/c/:category", element: <CategoryPage /> },
      { path: "/t/:tag", element: <TagPage /> },
      { path: "/p/:id", element: <PostDetail /> },
      { path: "/u/:handle", element: lazyEl(<ProfilePage />) },
      { path: "/u/:handle/followers", element: lazyEl(<ProfilePage tab="followers" />) },
      { path: "/u/:handle/following", element: lazyEl(<ProfilePage tab="following" />) },
      { path: "/search", element: lazyEl(<SearchPage />) },
      { path: "/help", element: lazyEl(<HelpPage />) },
      { path: "/notifications", element: authed(<NotificationsPage />) },
      { path: "/mod", element: <RequireMod>{lazyEl(<ModQueuePage />)}</RequireMod> },
      {
        path: "/settings",
        element: authed(<SettingsLayout />),
        children: [
          { index: true, element: <Navigate to="/settings/profile" replace /> },
          { path: "profile", element: lazyEl(<ProfileSettings />) },
          { path: "account", element: lazyEl(<AccountSettings />) },
          { path: "privacy", element: lazyEl(<Prefs.Privacy />) },
          { path: "content", element: lazyEl(<Prefs.Content />) },
          { path: "notifications", element: lazyEl(<Prefs.Notifications />) },
          { path: "blocked", element: lazyEl(<Prefs.Blocked />) },
          { path: "moderation", element: lazyEl(<ModerationHistory />) },
        ],
      },
      { path: "*", element: <NotFound /> },
    ],
  },
  {
    element: <BareLayout />,
    children: [
      { path: "/login", element: guest(<LoginPage />) },
      { path: "/signup", element: guest(<SignupPage />) },
      { path: "/forgot-password", element: <ForgotPasswordPage /> },
      { path: "/reset-password", element: <ResetPasswordPage /> },
      { path: "/verify-email", element: <VerifyEmailPage /> },
      { path: "/auth/callback", element: <AuthCallbackPage /> },
      { path: "/onboarding", element: <RequireAuth allowOnboarding><OnboardingPage /></RequireAuth> },
    ],
  },
]);
