import { Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from './auth/AuthContext'
import { LoadingBlock } from './components/feedback'
import { Shell } from './app/Shell'

import { LoginPage } from './pages/auth/LoginPage'
import { VerifyPage } from './pages/auth/VerifyPage'
import { StaffLinkPage } from './pages/auth/StaffLinkPage'
import { CreateOrganisationPage } from './pages/onboarding/CreateOrganisationPage'

import { ChefBriefPage } from './pages/chef-brief/ChefBriefPage'
import { RosterWeekPage } from './pages/roster/RosterWeekPage'
import { ShiftDetailPage } from './pages/roster/ShiftDetailPage'
import { PrepPage } from './pages/prep/PrepPage'
import { PrepTemplatesPage } from './pages/prep/PrepTemplatesPage'
import { PrepPrintablePage } from './pages/prep/PrepPrintablePage'
import { OrdersPage } from './pages/orders/OrdersPage'
import { PurchaseOrderDetailPage } from './pages/orders/PurchaseOrderDetailPage'
import { CapturePage } from './pages/capture/CapturePage'
import { HandoverPage } from './pages/handover/HandoverPage'
import { KitchenMemoryPage } from './pages/kitchen-memory/KitchenMemoryPage'
import { RecipeDetailPage } from './pages/kitchen-memory/RecipeDetailPage'
import { MenuItemDetailPage } from './pages/kitchen-memory/MenuItemDetailPage'
import { EquipmentIssueHistoryPage } from './pages/kitchen-memory/EquipmentIssueHistoryPage'
import { MorePage } from './pages/more/MorePage'
import { VenueSettingsPage } from './pages/more/VenueSettingsPage'
import { InvitePage } from './pages/more/InvitePage'
import { StaffingAdminPage } from './pages/more/StaffingAdminPage'
import { CatalogAdminPage } from './pages/more/CatalogAdminPage'
import { NotificationsAdminPage } from './pages/more/NotificationsAdminPage'
import { PilotMetricsPage } from './pages/more/PilotMetricsPage'

export function App() {
  const { status, me } = useAuth()

  return (
    <Routes>
      {/* Public — no auth required */}
      <Route path="/login" element={<LoginPage />} />
      <Route path="/verify" element={<VerifyPage />} />
      <Route path="/staff-links/:token" element={<StaffLinkPage />} />

      <Route path="/*" element={<Gate status={status} hasMembership={(me?.memberships.length ?? 0) > 0} />} />
    </Routes>
  )
}

function Gate({ status, hasMembership }: { status: 'loading' | 'signed_out' | 'signed_in'; hasMembership: boolean }) {
  if (status === 'loading') {
    return (
      <div className="min-h-dvh flex items-center justify-center">
        <LoadingBlock label="Loading Mise…" />
      </div>
    )
  }
  if (status === 'signed_out') return <Navigate to="/login" replace />
  if (!hasMembership) {
    return (
      <Routes>
        <Route path="/onboarding/new" element={<CreateOrganisationPage />} />
        <Route path="*" element={<Navigate to="/onboarding/new" replace />} />
      </Routes>
    )
  }

  return (
    <Shell>
      <Routes>
        <Route path="/" element={<ChefBriefPage />} />
        <Route path="/onboarding/new" element={<CreateOrganisationPage />} />

        <Route path="/roster" element={<RosterWeekPage />} />
        <Route path="/roster/shifts/:shiftId" element={<ShiftDetailPage />} />

        <Route path="/prep" element={<PrepPage />} />
        <Route path="/prep/templates" element={<PrepTemplatesPage />} />
        <Route path="/prep/printable" element={<PrepPrintablePage />} />

        <Route path="/orders" element={<OrdersPage />} />
        <Route path="/orders/:purchaseOrderId" element={<PurchaseOrderDetailPage />} />

        <Route path="/capture" element={<CapturePage />} />

        <Route path="/handover" element={<HandoverPage />} />
        <Route path="/handover/:businessDate" element={<HandoverPage />} />

        <Route path="/kitchen-memory" element={<KitchenMemoryPage />} />
        <Route path="/kitchen-memory/recipes/:recipeId" element={<RecipeDetailPage />} />
        <Route path="/kitchen-memory/menu-items/:menuItemId" element={<MenuItemDetailPage />} />
        <Route path="/kitchen-memory/equipment/:equipmentItemId" element={<EquipmentIssueHistoryPage />} />

        <Route path="/more" element={<MorePage />} />
        <Route path="/more/venue" element={<VenueSettingsPage />} />
        <Route path="/more/invite" element={<InvitePage />} />
        <Route path="/more/staffing" element={<StaffingAdminPage />} />
        <Route path="/more/catalog" element={<CatalogAdminPage />} />
        <Route path="/more/notifications" element={<NotificationsAdminPage />} />
        <Route path="/more/pilot-metrics" element={<PilotMetricsPage />} />

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Shell>
  )
}
