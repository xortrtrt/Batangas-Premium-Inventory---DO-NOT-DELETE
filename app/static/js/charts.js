(function () {
    function formatQuantity(value) {
        const quantity = Number(value || 0);
        return quantity.toLocaleString("en-US", {
            minimumFractionDigits: Number.isInteger(quantity) ? 0 : 2,
            maximumFractionDigits: Number.isInteger(quantity) ? 0 : 2,
        });
    }
    function bindInventoryMovementChart() {
        const canvas = document.querySelector("[data-inventory-movement-chart]");
        const payload = document.querySelector("[data-inventory-movement-json]");
        if (!canvas || !payload) {
            return;
        }

        let rows = [];
        try {
            rows = JSON.parse(payload.textContent || "[]");
        } catch (error) {
            rows = [];
        }

        if (!rows.length || !window.Chart) {
            return;
        }

        const labels = rows.map((row) => row.name);
        const stockIn = rows.map((row) => Number(row.total_in || 0));
        const stockOut = rows.map((row) => Number(row.total_out || 0));
        const units = rows.map((row) => row.unit || "pack");

        new window.Chart(canvas.getContext("2d"), {
            type: "bar",
            data: {
                labels,
                datasets: [
                    {
                        label: "Stock in",
                        data: stockIn,
                        backgroundColor: "rgba(223, 190, 29, 0.82)",
                        borderColor: "#d9b90f",
                        borderWidth: 1,
                        borderRadius: 8,
                    },
                    {
                        label: "Stock out",
                        data: stockOut,
                        backgroundColor: "rgba(91, 48, 25, 0.82)",
                        borderColor: "#5b3019",
                        borderWidth: 1,
                        borderRadius: 8,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                indexAxis: "y",
                scales: {
                    x: {
                        beginAtZero: true,
                        ticks: {
                            precision: 0,
                            color: "#675b44",
                        },
                        grid: {
                            color: "rgba(215, 201, 154, 0.45)",
                        },
                    },
                    y: {
                        ticks: {
                            color: "#23150f",
                            font: {
                                weight: 700,
                            },
                        },
                        grid: {
                            display: false,
                        },
                    },
                },
                plugins: {
                    legend: {
                        labels: {
                            color: "#23150f",
                            boxWidth: 14,
                            boxHeight: 14,
                            useBorderRadius: true,
                        },
                    },
                    tooltip: {
                        callbacks: {
                            label(context) {
                                const unit = units[context.dataIndex] || "pack";
                                return `${context.dataset.label}: ${formatQuantity(context.parsed.x)} ${unit}`;
                            },
                        },
                    },
                },
            },
        });

        const fallback = document.querySelector("[data-inventory-movement-fallback]");
        if (fallback) {
            fallback.hidden = true;
        }
    }
    bindInventoryMovementChart();
})();
