(function () {
    "use strict";

    // AI-assisted interface enhancement: staged reveal and number count-up.
    // Stock values remain server-rendered; these animations change presentation only.
    const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const revealNodes = document.querySelectorAll([
        ".page-heading",
        ".welcome-strip",
        ".recommendation-summary-card",
        ".recommendation-formula-card",
        ".recommendation-table-card",
        ".section-block",
        ".metric-card",
        ".dashboard-alert-grid > .content-card",
        ".secondary-grid > .content-card",
        ".next-step-card",
        ".batch-summary-card",
        ".sales-summary-card",
        ".product-filter-card",
        ".batch-form-layout",
        ".sale-form-layout",
        ".data-table-card",
        ".table-panel",
        ".movement-row"
    ].join(","));

    revealNodes.forEach(function (node, index) {
        node.classList.add("ww-reveal-init");
        node.style.setProperty("--ww-reveal-delay", Math.min(index % 5, 4) * 65 + "ms");
    });

    if (prefersReducedMotion || !("IntersectionObserver" in window)) {
        revealNodes.forEach(function (node) {
            node.classList.add("is-visible");
        });
    } else {
        const revealObserver = new IntersectionObserver(function (entries, observer) {
            entries.forEach(function (entry) {
                if (entry.isIntersecting) {
                    entry.target.classList.add("is-visible");
                    observer.unobserve(entry.target);
                }
            });
        }, { threshold: 0.12, rootMargin: "0px 0px -28px 0px" });

        revealNodes.forEach(function (node) {
            revealObserver.observe(node);
        });
    }

    if (!prefersReducedMotion) {
        const numberFormat = new Intl.NumberFormat("id-ID");
        document.querySelectorAll(".metric-value, .recommendation-summary-card [data-testid]").forEach(function (node) {
            const target = Number((node.textContent || "").trim().replace(/[^0-9-]/g, ""));
            if (!Number.isFinite(target) || target <= 0 || node.dataset.countAnimated === "true") {
                return;
            }

            node.dataset.countAnimated = "true";
            node.textContent = "0";
            const duration = 780;
            let startTime = null;

            function animateNumber(timestamp) {
                if (startTime === null) {
                    startTime = timestamp;
                }

                const progress = Math.min((timestamp - startTime) / duration, 1);
                const eased = 1 - Math.pow(1 - progress, 4);
                node.textContent = numberFormat.format(Math.round(target * eased));

                if (progress < 1) {
                    window.requestAnimationFrame(animateNumber);
                } else {
                    node.textContent = numberFormat.format(target);
                }
            }

            window.requestAnimationFrame(animateNumber);
        });
    }

    const productSelect = document.querySelector("[data-sale-product]");
    const quantityInput = document.querySelector("[data-sale-quantity]");
    const preview = document.querySelector("[data-sale-preview]");

    if (!productSelect || !quantityInput || !preview) {
        return;
    }

    const availableOutput = preview.querySelector("[data-sale-available]");
    const priceOutput = preview.querySelector("[data-sale-price]");
    const totalOutput = preview.querySelector("[data-sale-total]");
    const currency = new Intl.NumberFormat("id-ID", {
        style: "currency",
        currency: "IDR",
        maximumFractionDigits: 0
    });

    function refreshSalePreview() {
        const option = productSelect.options[productSelect.selectedIndex];
        const hasProduct = Boolean(option && option.value);
        const available = hasProduct ? Number(option.dataset.available || 0) : 0;
        const price = hasProduct ? Number(option.dataset.price || 0) : 0;
        const quantity = Number(quantityInput.value || 0);

        availableOutput.textContent = hasProduct
            ? available.toLocaleString("id-ID") + " " + (option.dataset.unit || "unit")
            : "Choose a product";
        priceOutput.textContent = hasProduct ? currency.format(price) : "—";
        totalOutput.textContent = hasProduct && quantity > 0
            ? currency.format(price * quantity)
            : "—";

        preview.classList.toggle(
            "sale-preview-warning",
            hasProduct && (available === 0 || quantity > available)
        );
        preview.classList.toggle(
            "sale-preview-ready",
            hasProduct && quantity > 0 && quantity <= available
        );
    }

    productSelect.addEventListener("change", refreshSalePreview);
    quantityInput.addEventListener("input", refreshSalePreview);
    refreshSalePreview();
}());
