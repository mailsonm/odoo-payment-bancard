# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import ValidationError


class BancardPosQrTransaction(models.Model):
    _name = 'bancard.pos.qr.transaction'
    _description = 'Transacción Bancard VentasQR en PDV (Odoo 19)'
    _order = 'create_date desc, id desc'

    name = fields.Char(
        string="Hook Alias (Bancard QR)",
        required=True,
        index=True,
        readonly=True,
        help="Identificador único (hook_alias) generado por el endpoint generate-qr-express de Bancard.",
    )
    pos_config_id = fields.Many2one(
        'pos.config',
        string="Punto de Venta (Sucursal)",
        required=True,
        index=True,
        ondelete='restrict',
    )
    pos_session_id = fields.Many2one(
        'pos.session',
        string="Sesión de Caja",
        index=True,
        ondelete='set null',
    )
    payment_method_id = fields.Many2one(
        'pos.payment.method',
        string="Método de Pago POS",
        ondelete='restrict',
    )
    pos_order_uuid = fields.Char(
        string="UUID del Pedido POS",
        index=True,
    )
    amount = fields.Integer(
        string="Monto en PYG (Guaraníes)",
        required=True,
        help="Monto entero en Guaraníes cobrado en el QR Express.",
    )
    description = fields.Char(
        string="Descripción",
    )
    qr_image_url = fields.Char(
        string="URL de la Imagen QR (PNG)",
        readonly=True,
    )
    qr_data = fields.Text(
        string="Payload EMVCo QR",
        readonly=True,
    )
    state = fields.Selection(
        selection=[
            ('pending', 'Esperando Lectura / Pago'),
            ('confirmed', 'Confirmado (Pagado)'),
            ('revert_requested', 'Revertido / Expirado en Caja'),
            ('reverted', 'Revertido en Bancard'),
            ('error', 'Error'),
        ],
        string="Estado",
        default='pending',
        required=True,
        index=True,
    )
    authorization_number = fields.Char(
        string="Número de Autorización",
        readonly=True,
    )
    ticket_number = fields.Char(
        string="Número de Boleta / Ticket",
        readonly=True,
    )
    response_payload = fields.Text(
        string="Payload de Confirmación / Auditoría",
        readonly=True,
    )
    active = fields.Boolean(
        string="Activo",
        default=True,
        help="Exclusión lógica (Soft Delete) universal.",
    )

    def unlink(self):
        """Prohíbe eliminación física de registros de auditoría financiera (Soft Delete obligatorio)."""
        raise ValidationError(
            _("Prohibido eliminar físicamente transacciones Bancard QR. Utilice el archivo lógico (active=False).")
        )
