/**
 * Customer Intelligence: a briefing on the top 10 accounts for sales and
 * finance leadership, and the same briefing for any one of them.
 *
 *   /customers        the top-10 briefing (TopTenBriefing)
 *   /customers/:id    one account (AccountBriefing)
 *
 * The narrative is insight records from v_insights; the figures beside it
 * come from /api/dashboards/customers/* (server/routes/dashboards/customers.py),
 * queried as the signed-in user like every dashboard.
 */
import { useEffect } from 'react'
import { Route, Routes, useLocation } from 'react-router-dom'
import AccountBriefing from './AccountBriefing'
import TopTenBriefing from './TopTenBriefing'

export default function CustomerIntelligencePage() {
  const { pathname } = useLocation()
  // <main> is the scroll container and outlives the route, so a new briefing
  // would otherwise open wherever the last one was scrolled to.
  useEffect(() => {
    document.querySelector('main')?.scrollTo({ top: 0 })
  }, [pathname])

  return (
    <Routes>
      <Route index element={<TopTenBriefing />} />
      <Route path=":customerId" element={<AccountBriefing />} />
    </Routes>
  )
}
