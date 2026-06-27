// plan-follow-dashboard — Hermes Dashboard Plugin (SDK v0.16+)
// Zeigt alle Pläne mit Status, Tasks und Statistiken an.

(function (SDK) {
    const { React, hooks, components } = SDK;
    const { useState, useEffect, useCallback } = hooks;
    const { Card, CardHeader, CardTitle, CardContent, Badge, Button, Table, TableHeader, TableRow, TableHead, TableBody, TableCell } = components;

    // Icons als einfache SVG-Spans
    const Icons = {
        list: React.createElement('svg', { width: 16, height: 16, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2 },
            React.createElement('line', { x1: 8, y1: 6, x2: 21, y2: 6 }),
            React.createElement('line', { x1: 8, y1: 12, x2: 21, y2: 12 }),
            React.createElement('line', { x1: 8, y1: 18, x2: 21, y2: 18 }),
            React.createElement('line', { x1: 3, y1: 6, x2: 3.01, y2: 6 }),
            React.createElement('line', { x1: 3, y1: 12, x2: 3.01, y2: 12 }),
            React.createElement('line', { x1: 3, y1: 18, x2: 3.01, y2: 18 }),
        ),
        check: React.createElement('svg', { width: 16, height: 16, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2 },
            React.createElement('polyline', { points: '20 6 9 17 4 12' }),
        ),
        clock: React.createElement('svg', { width: 16, height: 16, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2 },
            React.createElement('circle', { cx: 12, cy: 12, r: 10 }),
            React.createElement('polyline', { points: '12 6 12 12 16 14' }),
        ),
        refresh: React.createElement('svg', { width: 16, height: 16, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2 },
            React.createElement('polyline', { points: '23 4 23 10 17 10' }),
            React.createElement('path', { d: 'M20.49 15a9 9 0 1 1-2.12-9.36L23 10' }),
        ),
    };

    // Status-Badge Farbe
    function StatusBadge({ status }) {
        const colors = {
            completed: 'bg-green-500/20 text-green-500',
            in_progress: 'bg-blue-500/20 text-blue-500',
            pending: 'bg-gray-500/20 text-gray-400',
            aborted: 'bg-red-500/20 text-red-500',
            blocked: 'bg-yellow-500/20 text-yellow-500',
        };
        const labels = {
            completed: '✅ Done',
            in_progress: '▶️ Active',
            pending: '⏳ Pending',
            aborted: '⛔ Aborted',
            blocked: '🚫 Blocked',
        };
        const colorClass = colors[status] || 'bg-gray-500/20 text-gray-400';
        return React.createElement('span', {
            className: `px-2 py-0.5 rounded text-xs font-medium ${colorClass}`,
        }, labels[status] || status);
    }

    // Haupt-Panel: Plan-Liste
    function PlansTab() {
        const [plans, setPlans] = useState([]);
        const [stats, setStats] = useState(null);
        const [loading, setLoading] = useState(true);
        const [selectedPlan, setSelectedPlan] = useState(null);
        const [planTasks, setPlanTasks] = useState([]);

        const fetchPlans = useCallback(async () => {
            try {
                const res = await SDK.fetchJSON('/api/plugins/plan-follow-dashboard/plans?limit=30');
                setPlans(res.plans || []);
            } catch (e) {
                console.error('Failed to fetch plans:', e);
            }
        }, []);

        const fetchStats = useCallback(async () => {
            try {
                const res = await SDK.fetchJSON('/api/plugins/plan-follow-dashboard/stats');
                setStats(res);
            } catch (e) {
                console.error('Failed to fetch stats:', e);
            }
        }, []);

        const fetchPlanDetail = useCallback(async (planId) => {
            try {
                const res = await SDK.fetchJSON(`/api/plugins/plan-follow-dashboard/plans/${encodeURIComponent(planId)}`);
                setSelectedPlan(res);
                setPlanTasks(res.tasks || []);
            } catch (e) {
                console.error('Failed to fetch plan:', e);
            }
        }, []);

        useEffect(() => {
            Promise.all([fetchPlans(), fetchStats()]).finally(() => setLoading(false));
        }, [fetchPlans, fetchStats]);

        if (loading) {
            return React.createElement('div', { className: 'flex items-center justify-center py-20' },
                React.createElement('div', { className: 'animate-spin' }, Icons.refresh),
                React.createElement('span', { className: 'ml-2 text-gray-400' }, 'Loading plans...'),
            );
        }

        // Detail-Ansicht
        if (selectedPlan) {
            return React.createElement('div', { className: 'space-y-4' },
                React.createElement('div', { className: 'flex items-center gap-2' },
                    React.createElement(Button, {
                        variant: 'ghost',
                        onClick: () => { setSelectedPlan(null); setPlanTasks([]); },
                        className: 'text-gray-400 hover:text-white',
                    }, '← Back'),
                    React.createElement('h2', { className: 'text-lg font-semibold' }, selectedPlan.goal || selectedPlan.plan_id),
                ),
                React.createElement(Card, null,
                    React.createElement(CardHeader, null,
                        React.createElement(CardTitle, null, 'Tasks (', selectedPlan.task_count, ')'),
                    ),
                    React.createElement(CardContent, null,
                        planTasks.length === 0
                            ? React.createElement('p', { className: 'text-gray-400' }, 'No tasks in this plan.')
                            : React.createElement(Table, null,
                                React.createElement(TableHeader, null,
                                    React.createElement(TableRow, null,
                                        React.createElement(TableHead, null, 'ID'),
                                        React.createElement(TableHead, null, 'Name'),
                                        React.createElement(TableHead, null, 'Status'),
                                        React.createElement(TableHead, null, 'Profile'),
                                    ),
                                ),
                                React.createElement(TableBody, null,
                                    planTasks.map(task => React.createElement(TableRow, { key: task.id },
                                        React.createElement(TableCell, { className: 'font-mono text-xs' }, task.id),
                                        React.createElement(TableCell, null, task.name),
                                        React.createElement(TableCell, null,
                                            React.createElement(StatusBadge, { status: task.status })
                                        ),
                                        React.createElement(TableCell, null,
                                            React.createElement('span', {
                                                className: `px-2 py-0.5 rounded text-xs ${
                                                    task.review_state === 'passed' ? 'bg-green-500/20 text-green-500' :
                                                    task.review_state ? 'bg-yellow-500/20 text-yellow-500' :
                                                    'bg-gray-500/20 text-gray-400'
                                                }`,
                                            }, task.review_profile !== 'none' ? (task.review_state || 'pending') : '-')
                                        ),
                                    )),
                                ),
                            ),
                    ),
                ),
            );
        }

        // Übersicht
        return React.createElement('div', { className: 'space-y-6' },
            // Stats Cards
            stats && React.createElement('div', { className: 'grid grid-cols-2 lg:grid-cols-4 gap-4' },
                Object.entries({
                    'Total Plans': stats.total_plans,
                    'Active Plans': stats.active_plans,
                    'Completed Tasks': stats.completed_tasks,
                    'Completion Rate': stats.completion_rate + '%',
                }).map(([label, value]) => React.createElement(Card, { key: label },
                    React.createElement(CardHeader, { className: 'pb-2' },
                        React.createElement(CardTitle, { className: 'text-sm text-gray-400' }, label),
                    ),
                    React.createElement(CardContent, null,
                        React.createElement('p', { className: 'text-2xl font-bold' }, value),
                    ),
                )),
            ),

            // Plan List
            React.createElement(Card, null,
                React.createElement(CardHeader, { className: 'flex flex-row items-center justify-between' },
                    React.createElement(CardTitle, null, 'Alle Pläne'),
                    React.createElement(Button, {
                        variant: 'ghost',
                        size: 'sm',
                        onClick: () => { setLoading(true); Promise.all([fetchPlans(), fetchStats()]).finally(() => setLoading(false)); },
                    }, Icons.refresh, ' Refresh'),
                ),
                React.createElement(CardContent, null,
                    plans.length === 0
                        ? React.createElement('p', { className: 'text-gray-400' }, 'No plans yet. Create one with plan_create()!')
                        : React.createElement('div', { className: 'space-y-2' },
                            plans.map(plan => React.createElement('div', {
                                key: plan.plan_id,
                                className: 'flex items-center justify-between p-3 rounded-lg bg-white/5 hover:bg-white/10 cursor-pointer transition-colors',
                                onClick: () => fetchPlanDetail(plan.plan_id),
                            },
                                React.createElement('div', { className: 'flex-1 min-w-0' },
                                    React.createElement('p', { className: 'font-medium truncate' }, plan.goal || plan.plan_id),
                                    React.createElement('p', { className: 'text-xs text-gray-400 mt-0.5' },
                                        plan.created ? new Date(plan.created).toLocaleDateString() : '',
                                        ' · ', plan.task_count, ' tasks',
                                        plan.current_task ? ' · ▶️ ' + plan.current_task : '',
                                    ),
                                ),
                                React.createElement('div', { className: 'flex items-center gap-2 shrink-0' },
                                    Object.entries(plan.status_summary || {}).map(([status, count]) =>
                                        React.createElement(Badge, {
                                            key: status,
                                            variant: status === 'completed' ? 'secondary' : 'outline',
                                            className: 'text-xs',
                                        }, status, ': ', count),
                                    ),
                                ),
                            )),
                        ),
                ),
            ),
        );
    }

    // Plugin registrieren
    SDK.registerTab('plans', {
        label: '📋 Plans',
        component: PlansTab,
        icon: 'list-checks',
    });

})(window.__HERMES_PLUGIN_SDK__);
