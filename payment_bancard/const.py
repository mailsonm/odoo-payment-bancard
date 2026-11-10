# -*- coding: utf-8 -*-

DEFAULT_PAYMENT_METHOD_CODES = {
    'card',
}

SUPPORTED_CURRENCIES = (
    'PYG',
    'BRL',
    'USD',
)

BANCARD_CHECKOUT_JS_VERSION = '5.0.1'
BANCARD_DESCRIPTION_MAX_LEN = 20

BANCARD_STAGING_URL = 'https://vpos.infonet.com.py:8888'
BANCARD_PRODUCTION_URL = 'https://vpos.infonet.com.py'

BANCARD_QR_STAGING_URL = 'https://comercios.bancard.com.py:8888'
BANCARD_QR_PRODUCTION_URL = 'https://comercios.bancard.com.py'

BANCARD_API_VERSION = '0.3'
BANCARD_QR_API_VERSION = '0.1'

BANCARD_ENDPOINTS = {
    'single_buy': f'/vpos/api/{BANCARD_API_VERSION}/single_buy',
    'cards_new': f'/vpos/api/{BANCARD_API_VERSION}/cards/new',
    'users_cards': f'/vpos/api/{BANCARD_API_VERSION}/users/{{user_id}}/cards',
    'charge': f'/vpos/api/{BANCARD_API_VERSION}/charge',
    'confirmations': f'/vpos/api/{BANCARD_API_VERSION}/single_buy/confirmations',
    'rollback': f'/vpos/api/{BANCARD_API_VERSION}/single_buy/rollback',
}

# === Constantes da Integração Bancard Caja POS 3.0 (Terminal Físico / Pinpad REST) ===
BANCARD_CAJAPOS_STAGING_URL = 'https://cajapos-qa.bancard.com.py'
BANCARD_CAJAPOS_PRODUCTION_URL = 'https://cajapos.bancard.com.py'
BANCARD_CAJAPOS_CURRENCY_CODE = '600'  # 600 = Gs. (Guaraníes)
BANCARD_CAJAPOS_TX_TYPE_CONTADO = 'VENTA_CONTADO'

BANCARD_CAJAPOS_ENDPOINTS = {
    'venta': '/v1/external/pos/venta',
    'consulta': '/v1/external/pos/venta/{token}',
}

BANCARD_CAJAPOS_FINAL_STATES = (
    'CANCELLED',
    'PAYMENT_CONFIRMED',
    'PAYMENT_REJECTED',
    'PAYMENT_CANCELLED',
)

BANCARD_RESPONSE_CODES = {
    '00': 'Transacción Aprobada',
    '01': 'Refiérase al Emisor',
    '02': 'Refiérase al Emisor - Condición Especial',
    '03': 'Comercio Inválido',
    '04': 'Retener Tarjeta',
    '05': 'No Aprobado / Tarjeta Inhabilitada',
    '12': 'Transacción Inválida',
    '13': 'Monto Inválido',
    '14': 'Número de Tarjeta Inválido',
    '15': 'Emisor Inválido',
    '19': 'Reintente la Transacción',
    '30': 'Error de Formato',
    '33': 'Tarjeta Vencida',
    '41': 'Tarjeta Perdida - Retener',
    '43': 'Tarjeta Robada - Retener',
    '51': 'Fondos Insuficientes',
    '54': 'Tarjeta Vencida',
    '55': 'PIN Incorrecto',
    '57': 'Transacción no Permitida al Titular',
    '58': 'Transacción no Permitida a la Terminal',
    '61': 'Excede Límite de Monto',
    '65': 'Excede Límite de Frecuencia',
    '91': 'Emisor o Switch no Disponible',
    '94': 'Transacción Duplicada',
    '96': 'Mal Funcionamiento del Sistema',
}
