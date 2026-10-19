(function () {
    "use strict";

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
