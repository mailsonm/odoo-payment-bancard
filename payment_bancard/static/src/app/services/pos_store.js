import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/services/pos_store";

patch(PosStore.prototype, {
    async setup() {
        await super.setup(...arguments);
        this.data.connectWebSocket("BANCARD_QR_PAYMENT_STATUS", (payload) => {
            if (payload.config_id === this.config.id) {
                const pendingLine = this.getPendingPaymentLine("bancard_qr");
                if (pendingLine && pendingLine.payment_method_id?.payment_terminal) {
                    pendingLine.payment_method_id.payment_terminal.handleBancardQRWebhook(payload);
                }
            }
        });
    },
});
