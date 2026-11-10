# -*- coding: utf-8 -*-
from odoo import fields, models


class BancardPosCajaposTransaction(models.Model):
    _name = 'bancard.pos.cajapos.transaction'
    _description = 'Transacción Bancard Caja POS 3.0 en PDV (Terminal Físico / Pinpad)'
    _order = 'create_date desc, id desc'

    name = fields.Char(
        string="Token de la Transacción (txToken)",
        required=True,
        index=True,
        readonly=True,
        help="Token único identificador retornado por el endpoint /v1/external/pos/venta de Bancard.",
    )
    active = fields.Boolean(
        string="Activo",
        default=True,
        help="Soft delete: desactive el registro en lugar de eliminarlo físicamente.",
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
    bill_number = fields.Char(
        string="Número de Factura / Comprobante ERP",
        required=True,
        help="Número de la factura o pedido enviado a la terminal física.",
    )
    pos_code = fields.Char(
        string="Código del Terminal POS Físico (posCode)",
        required=True,
        help="Identificador de la terminal física Bancard configurada en esta caja.",
    )
    provider_id = fields.Char(
        string="Provider ID (4 dígitos)",
        default='0001',
        required=True,
    )
    amount = fields.Integer(
        string="Monto en PYG (Guaraníes)",
        required=True,
        help="Monto entero en Guaraníes sin decimales enviado para cobro en la terminal.",
    )
    currency_code = fields.Char(
        string="Código de Moneda ISO/Bancard",
        default='600',
        readonly=True,
    )
    tx_type = fields.Char(
        string="Tipo de Transacción",
        default='VENTA_CONTADO',
        readonly=True,
    )
    state = fields.Selection(
        selection=[
            ('created', 'Creada (Antes del Terminal)'),
            ('payment_pending', 'Esperando Pagador en Terminal'),
            ('payment_confirmed', 'Pago Confirmado'),
            ('payment_rejected', 'Rechazado por Bancard'),
            ('payment_cancelled', 'Cancelado por el Cliente en Terminal'),
            ('cancelled', 'Cancelado / Terminal Offline'),
            ('error', 'Error de Comunicación'),
        ],
        string="Estado",
        default='created',
        required=True,
        index=True,
    )

    # Detalles del comprobante retornados en additionalInfo.bancardInfo
    ticket_number = fields.Char(string="Número de Boleta (ticketNumber)", readonly=True)
    authorization_code = fields.Char(string="Código de Autorización", readonly=True)
    date_time = fields.Char(string="Fecha/Hora de la Transacción (Terminal)", readonly=True)
    amount_buy = fields.Char(string="Monto Cobrado", readonly=True)
    amount_change = fields.Char(string="Vuelto", readonly=True)
    installment_number = fields.Char(string="Cuotas", readonly=True)
    payment_description = fields.Char(string="Descripción del Método de Pago", readonly=True)
    card_last_numbers = fields.Char(string="Últimos 4 Dígitos de la Tarjeta", readonly=True)
    cardholder_name = fields.Char(string="Nombre del Tarjetahabiente", readonly=True)
    read_type = fields.Char(
        string="Tipo de Lectura (T=Tarjeta, B=Billetera, QR=QR)",
        readonly=True,
        help="T = Tarjeta (chip/aproximación/banda), B = Billetera móvil, QR = QR en pantalla de la terminal.",
    )
    issuer_id = fields.Char(string="ID del Emisor", readonly=True)
    account_type = fields.Char(string="Tipo de Cuenta", readonly=True)
    merchant_code = fields.Char(string="Código del Comercio (Bancard)", readonly=True)
    device_model = fields.Char(string="Modelo del POS", readonly=True)
    device_serial = fields.Char(string="Número de Serie del POS", readonly=True)
    device_version = fields.Char(string="Versión de la Aplicación (Hermes/Iris)", readonly=True)
    response_code = fields.Char(string="Código de Respuesta", readonly=True)
    response_message = fields.Char(string="Mensaje de Respuesta", readonly=True)
    response_payload = fields.Text(string="Payload Completo de Bancard", readonly=True)
