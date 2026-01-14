import { createRouter, createWebHistory } from "vue-router";
import OverviewPage from "./pages/Overview.vue";
import ReportsPage from "./pages/Reports.vue";
import ReportDetailPage from "./pages/ReportDetail.vue";
import SettingsPage from "./pages/Settings.vue";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "overview", component: OverviewPage },
    { path: "/reports", name: "reports", component: ReportsPage },
    { path: "/reports/view", name: "report-detail", component: ReportDetailPage },
    { path: "/settings", name: "settings", component: SettingsPage },
  ],
});

export default router;
