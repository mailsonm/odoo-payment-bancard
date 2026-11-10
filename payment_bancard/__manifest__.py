# -*- coding: utf-8 -*-
{
    'name': "Payment Provider: Bancard (vPOS 2.0, POS QR & Caja POS 3.0)",
    'version': '19.0.2.0.0',
    'category': 'Accounting/Payment Providers',
    'sequence': 350,
    'summary': "Integración Bancard vPOS 2.0 (Tarjetas, 3DS, PIX), VentasQR v1.2 y Terminal Físico Caja POS 3.0 en PDV para Odoo 19.",
    'description': """
Integración Oficial Bancard Paraguay para Odoo 19 Community & Enterprise
========================================================================
- **vPOS 2.0 API:** Pago individual (`single_buy`), Tokenización de hasta 5 tarjetas (`cards/new`, `charge`), 3DS (`Charge3DS`), PIX Online y Rollback/Reembolso.
- **Multimoneda de Frontera:** Conversión automática de `BRL` y `USD` a `PYG` (Guaraníes).
- **VentasQR v1.2 en PDV (`point_of_sale`):** QR Dinámico Express por sucursal (`commerce_code` / `branch_code`), reversión con protección contra cobro doble (`revert_requested`) y confirmación en tiempo real.
- **Caja POS 3.0 REST en PDV:** Accionamiento directo de la terminal física de mostrador (Smart POS Android T6/Iris/Hermes) con autenticación JWT HS256, polling asíncrono e impresión de comprobante en la terminal.
    """,
    'author': "Mailson Maia Alves",
    'website': "https://github.com/mailsonm/odoo-payment-bancard",
    'depends': ['payment', 'account', 'point_of_sale'],
    'data': [
        'security/ir.model.access.csv',
        'views/payment_bancard_templates.xml',
        'views/payment_provider_views.xml',
        'views/payment_transaction_views.xml',
        'views/pos_config_views.xml',
        'views/bancard_pos_qr_views.xml',
        'views/bancard_pos_cajapos_views.xml',
        'data/payment_provider_data.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'payment_bancard/static/src/scss/payment_bancard.scss',
            'payment_bancard/static/src/interactions/payment_form.js',
        ],
        'point_of_sale._assets_pos': [
            'payment_bancard/static/src/app/**/*',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
