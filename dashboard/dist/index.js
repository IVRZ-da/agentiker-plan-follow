// plan-follow-dashboard — Hermes Dashboard Plugin (SDK v0.16+)
// Zeigt Pläne aus Kanban-DB oder JSON-Backend mit Status, Tasks und Stats.
(function (SDK) {
    const { React, hooks, components } = SDK;
    const { useState, useEffect, useCallback } = hooks;
    const { Card, CardHeader, CardTitle, CardContent, Badge, Button, Table, TableHeader, TableRow, TableHead, TableBody, TableCell } = components;

    const API_BASE = '/api/plugins/plan-follow-dashboard';

    // Icons
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
        database: React.createElement('svg', { width: 16, height: 16, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2 },
            React.createElement('ellipse', { cx: 12, cy: 5, rx: 9, ry: 3 }),
            React.createElement('path', { d: 'M21 12c0 1.66-4 3-9 3s-9-1.34-9-3' }),
            React.createElement('path', { d: 'M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5' }),
        ),
    };

    // Status-Badge Farbe
    function StatusBadge({ status }) {
        const colors = {
            completed: 'bg-green-500/20 text-green-500',
            in_progress: 'bg-blue-500/20 text-blue-500',
            running: 'bg-blue-500/20 text-blue-500',
            pending: 'bg-gray-500/20 text-gray-400',
            todo: 'bg-gray-500/20 text-gray-400',
            ready: 'bg-cyan-500/20 text-cyan-400',
            aborted: 'bg-red-500/20 text-red-500',
            blocked: 'bg-yellow-500/20 text-yellow-500',
            failed: 'bg-red-500/20 text-red-500',
        };
        const color = colors[status] || 'bg-gray-500/20 text-gray-400';
        return React.createElement(Badge, { className: color }, status);
    }

    // ─── Backend Indicator ────────────────────────────────────────
    function BackendBadge({ backend }) {
        if (backend === 'kanban') {
            return React.createElement(Badge, { className: 'bg-emerald-500/20 text-emerald-400 ml-2' },
                React.createElement(Icons.database.type, { ...Icons.database.props, width: 12, height: 12 }),
                ' Kanban'
            );
        }
        return React.createElement(Badge, { className: 'bg-amber-500/20 text-amber-400 ml-2' },
            ' JSON'
        );
    }

    // ─── Main App ─────────────────────────────────────────────────
    function PlansApp() {
        const [plans, setPlans] = useState([]);
        const [stats, setStats] = useState(null);
        const [loading, setLoading] = useState(true);
        const [error, setError] = useState(null);
        const [selectedPlan, setSelectedPlan] = useState(null);
        const [backend, setBackend] = useState('json');

        const fetchData = useCallback(async () => {
            try {
                // Get backend info
                const bkResp = await fetch(API_BASE + '/backends', { credentials: 'same-origin' });
                const bkData = await bkResp.json();
                setBackend(bkData.active_backend || 'json');

                // Get plans
                const plansResp = await fetch(API_BASE + '/plans?limit=50', { credentials: 'same-origin' });
                const plansData = await plansResp.json();
                setPlans(plansData.plans || []);

                // Get stats
                const statsResp = await fetch(API_BASE + '/stats', { credentials: 'same-origin' });
                const statsData = await statsResp.json();
                setStats(statsData);
            } catch (err) {
                setError(err.message);
            } finally {
                setLoading(false);
            }
        }, []);

        useEffect(() => { fetchData(); }, [fetchData]);

        const loadPlanDetail = useCallback(async (planId) => {
            try {
                const resp = await fetch(API_BASE + '/plans/' + encodeURIComponent(planId), { credentials: 'same-origin' });
                if (!resp.ok) throw new Error('Plan not found');
                const data = await resp.json();
                setSelectedPlan(data);
            } catch (err) {
                setError(err.message);
            }
        }, []);

        if (loading) {
            return React.createElement('div', { className: 'flex items-center justify-center h-64' },
                React.createElement('div', { className: 'text-gray-400' }, 'Lade Pläne...')
            );
        }

        if (error) {
            return React.createElement('div', { className: 'text-red-400 p-4' }, 'Fehler: ' + error);
        }

        // ─── Detail-Ansicht ────────────────────────────────────
        if (selectedPlan) {
            const plan = selectedPlan;
            const taskRows = (plan.tasks || []).map(t =>
                React.createElement(TableRow, { key: t.id },
                    React.createElement(TableCell, null, t.id),
                    React.createElement(TableCell, null, t.name),
                    React.createElement(TableCell, null,
                        React.createElement(StatusBadge, { status: t.status })),
                    React.createElement(TableCell, null, t.assignee || '-'),
                    React.createElement(TableCell, null, (t.files || []).slice(0, 2).join(', ') || '-'),
                )
            );

            return React.createElement('div', { className: 'p-4' },
                React.createElement(Button, {
                    onClick: () => setSelectedPlan(null),
                    className: 'mb-4',
                }, '← Zurück'),
                React.createElement(Card, null,
                    React.createElement(CardHeader, null,
                        React.createElement(CardTitle, null,
                            plan.goal,
                            React.createElement(BackendBadge, { backend: plan.source || backend }),
                        ),
                    ),
                    React.createElement(CardContent, null,
                        React.createElement('div', { className: 'grid grid-cols-3 gap-4 mb-4' },
                            React.createElement('div', null,
                                React.createElement('div', { className: 'text-sm text-gray-400' }, 'Plan-ID'),
                                React.createElement('div', { className: 'font-mono text-sm' }, plan.plan_id),
                            ),
                            React.createElement('div', null,
                                React.createElement('div', { className: 'text-sm text-gray-400' }, 'Tasks'),
                                React.createElement('div', { className: 'font-mono text-sm' }, plan.task_count),
                            ),
                            React.createElement('div', null,
                                React.createElement('div', { className: 'text-sm text-gray-400' }, 'Status'),
                                React.createElement('div', null,
                                    React.createElement(StatusBadge, { status: plan.status || (plan.current_task ? 'in_progress' : 'completed') }),
                                ),
                            ),
                        ),
                        React.createElement(Table, null,
                            React.createElement(TableHeader, null,
                                React.createElement(TableRow, null,
                                    React.createElement(TableHead, null, 'ID'),
                                    React.createElement(TableHead, null, 'Name'),
                                    React.createElement(TableHead, null, 'Status'),
                                    React.createElement(TableHead, null, 'Assignee'),
                                    React.createElement(TableHead, null, 'Files'),
                                ),
                            ),
                            React.createElement(TableBody, null, taskRows),
                        ),
                    ),
                ),
            );
        }

        // ─── Übersichts-Ansicht ─────────────────────────────────
        return React.createElement('div', { className: 'p-4' },
            // Stats Cards
            React.createElement('div', { className: 'grid grid-cols-2 md:grid-cols-4 gap-4 mb-6' },
                React.createElement(Card, null,
                    React.createElement(CardHeader, null,
                        React.createElement(CardTitle, { className: 'text-lg' }, 'Pläne'),
                    ),
                    React.createElement(CardContent, null,
                        React.createElement('div', { className: 'text-2xl font-bold' },
                            stats ? stats.total_plans : plans.length),
                        React.createElement('div', { className: 'text-xs text-gray-400' },
                            stats ? (stats.active_plans + ' aktiv') : ''),
                    ),
                ),
                React.createElement(Card, null,
                    React.createElement(CardHeader, null,
                        React.createElement(CardTitle, { className: 'text-lg' }, 'Erledigt'),
                    ),
                    React.createElement(CardContent, null,
                        React.createElement('div', { className: 'text-2xl font-bold text-green-400' },
                            stats ? stats.completed_tasks : '—'),
                    ),
                ),
                React.createElement(Card, null,
                    React.createElement(CardHeader, null,
                        React.createElement(CardTitle, { className: 'text-lg' }, 'Offen'),
                    ),
                    React.createElement(CardContent, null,
                        React.createElement('div', { className: 'text-2xl font-bold text-yellow-400' },
                            stats ? stats.pending_tasks : '—'),
                    ),
                ),
                React.createElement(Card, null,
                    React.createElement(CardHeader, null,
                        React.createElement(CardTitle, { className: 'text-lg' }, 'Fertig %'),
                    ),
                    React.createElement(CardContent, null,
                        React.createElement('div', { className: 'text-2xl font-bold text-blue-400' },
                            stats ? (stats.completion_rate || 0) + '%' : '—'),
                    ),
                ),
            ),

            // Backend & Refresh
            React.createElement('div', { className: 'flex items-center justify-between mb-4' },
                React.createElement('div', { className: 'flex items-center gap-2' },
                    React.createElement('h2', { className: 'text-lg font-semibold' }, 'Alle Pläne'),
                    React.createElement(BackendBadge, { backend: backend }),
                ),
                React.createElement(Button, { onClick: fetchData, className: 'flex items-center gap-1' },
                    React.createElement(Icons.refresh.type, { ...Icons.refresh.props, width: 14, height: 14 }),
                    ' Aktualisieren',
                ),
            ),

            // Plan-Liste
            plans.length === 0
                ? React.createElement('div', { className: 'text-gray-400 text-center py-8' },
                    'Keine Pläne gefunden. Erstelle einen Plan mit plan_create().')
                : React.createElement('div', { className: 'space-y-2' },
                    plans.map(plan =>
                        React.createElement(Card, {
                            key: plan.plan_id,
                            className: 'cursor-pointer hover:bg-white/5 transition-colors',
                            onClick: () => loadPlanDetail(plan.plan_id),
                        },
                            React.createElement(CardContent, { className: 'flex items-center justify-between py-3' },
                                React.createElement('div', { className: 'flex-1' },
                                    React.createElement('div', { className: 'font-medium' },
                                        plan.goal || plan.plan_id),
                                    React.createElement('div', { className: 'text-xs text-gray-400 mt-1' },
                                        plan.plan_id.slice(0, 40)),
                                ),
                                React.createElement('div', { className: 'flex items-center gap-3' },
                                    React.createElement('span', { className: 'text-xs text-gray-400' },
                                        plan.task_count + ' Tasks'),
                                    React.createElement(StatusBadge, {
                                        status: plan.current_task ? 'in_progress' : 'completed'
                                    }),
                                    React.createElement(Icons.list.type, {
                                        ...Icons.list.props,
                                        className: 'text-gray-400',
                                        width: 16, height: 16,
                                    }),
                                ),
                            ),
                        ),
                    ),
                ),
        );
    }

    return PlansApp;
})(window.SDK);