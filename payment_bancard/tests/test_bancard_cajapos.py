# -*- coding: utf-8 -*-
import base64
import hashlib
import hmac
import json
import time
from unittest.mock import patch, MagicMock

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install', 'payment_bancard')
class TestBancardCajaPos(TransactionCase):
    """Suíte TDD para a integração Bancard Caja POS 3.0 (Terminal Físico no Balcão)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.currency_pyg = cls.env.ref('base.PYG', raise_if_not_found=False) or cls.env['res.currency'].search([('name', '=', 'PYG')], limit=1)
        if cls.currency_pyg:
            cls.currency_pyg.sudo().write({'active': True})

        cls.pos_config = cls.env['pos.config'].create({
            'name': 'Caixa Piloto Balcão - Caja POS 3.0',
            'bancard_cajapos_enabled': True,
            'bancard_cajapos_environment': 'test',
            'bancard_cajapos_commerce_code': 'ROSHKA-COMMERCE-TEST',
            'bancard_cajapos_api_key': 'secret_api_key_hs256_test_fa',
            'bancard_cajapos_pos_code': 'pos2342',
            'bancard_cajapos_provider_id': '0001',
            'bancard_cajapos_print_voucher': True,
        })

        cls.payment_method = cls.env['pos.payment.method'].create({
            'name': 'Bancard Terminal Pinpad (Caja POS 3.0)',
            'use_payment_terminal': 'bancard_cajapos',
            'company_id': cls.env.company.id,
        })

    def test_01_cajapos_jwt_generation_and_claims(self):
        """Valida que o JWT é assinado com HS256, contém claims commerce e tstamp e é válido por 5 min."""
        commerce = 'ROSHKA-COMMERCE-TEST'
        api_key = 'secret_api_key_hs256_test_fa'

        jwt_token = self.payment_method._bancard_cajapos_build_jwt(commerce, api_key)
        self.assertTrue(jwt_token)

        parts = jwt_token.split('.')
        self.assertEqual(len(parts), 3, "JWT deve ter exatamente 3 partes: header.payload.signature")

        header_json = base64.urlsafe_b64decode(parts[0] + '===').decode('utf-8')
        header = json.loads(header_json)
        self.assertEqual(header.get('alg'), 'HS256')
        self.assertEqual(header.get('typ'), 'JWT')

        payload_json = base64.urlsafe_b64decode(parts[1] + '===').decode('utf-8')
        payload = json.loads(payload_json)
        self.assertEqual(payload.get('commerce'), commerce)
        now = int(time.time())
        self.assertAlmostEqual(payload.get('tstamp'), now, delta=10)

        # Recalcular a assinatura HMAC-SHA256
        msg = f"{parts[0]}.{parts[1]}".encode('utf-8')
        expected_sig = base64.urlsafe_b64encode(
            hmac.new(api_key.encode('utf-8'), msg, hashlib.sha256).digest()
        ).decode('utf-8').rstrip('=')
        self.assertEqual(parts[2], expected_sig, "A assinatura HMAC-SHA256 deve coincidir com o cálculo oficial")

    def test_02_cajapos_credentials_validation(self):
        """Valida que providerId deve conter exatamente 4 dígitos numéricos e posCode é obrigatório."""
        # Provider ID com letras ou tamanho diferente de 4 dígitos deve falhar
        self.pos_config.write({'bancard_cajapos_provider_id': '12'})
        with self.assertRaises(ValidationError):
            self.pos_config._bancard_cajapos_get_credentials()

        self.pos_config.write({'bancard_cajapos_provider_id': '0001', 'bancard_cajapos_pos_code': ''})
        with self.assertRaises(ValidationError):
            self.pos_config._bancard_cajapos_get_credentials()

        self.pos_config.write({'bancard_cajapos_pos_code': 'pos2342'})
        creds = self.pos_config._bancard_cajapos_get_credentials()
        self.assertEqual(creds['commerce_code'], 'ROSHKA-COMMERCE-TEST')
        self.assertEqual(creds['provider_id'], '0001')
        self.assertEqual(creds['pos_code'], 'pos2342')

    @patch('odoo.addons.payment_bancard.models.pos_payment_method.requests.Session.request')
    def test_03_create_sale_post_and_pending_status(self, mock_request):
        """Valida envio da venda ao terminal físico (POST /v1/external/pos/venta) e persistência do txToken."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'token': 'TRN-CAJAPOS-998877',
            'tstamp': '2026-10-22',
            'status': 'PAYMENT_PENDING',
            'amount': 150000,
            'currency': '600',
            'txType': 'VENTA_CONTADO',
            'ticketNumber': None,
            'resultCode': None,
        }
        mock_request.return_value = mock_response

        infos = {
            'pos_config_id': self.pos_config.id,
            'bill_number': 'FAC-001-002-12345',
            'amount': 150000,
            'pos_order_uuid': 'ORDER-UUID-999',
        }

        res = self.payment_method.bancard_cajapos_create_sale(infos)

        self.assertEqual(res['status'], 'success')
        self.assertEqual(res['tx_token'], 'TRN-CAJAPOS-998877')
        self.assertEqual(res['payment_status'], 'PAYMENT_PENDING')

        # Verificar se chamou o endpoint com o payload correto
        mock_request.assert_called_once()
        called_kwargs = mock_request.call_args[1]
        self.assertEqual(called_kwargs['method'], 'POST')
        self.assertTrue(called_kwargs['url'].endswith('/v1/external/pos/venta'))
        payload = called_kwargs['json']
        self.assertEqual(payload['commerceCode'], 'ROSHKA-COMMERCE-TEST')
        self.assertEqual(payload['posCode'], 'pos2342')
        self.assertEqual(payload['providerId'], '0001')
        self.assertEqual(payload['billNumber'], 'FAC-001-002-12345')
        self.assertEqual(payload['amount'], 150000)
        self.assertEqual(payload['currencyCode'], '600')
        self.assertEqual(payload['txType'], 'VENTA_CONTADO')
        self.assertTrue(payload['printVoucher'])

        # Verificar auditoria em bancard.pos.cajapos.transaction
        tx = self.env['bancard.pos.cajapos.transaction'].search([
            ('name', '=', 'TRN-CAJAPOS-998877')
        ], limit=1)
        self.assertTrue(tx)
        self.assertEqual(tx.state, 'payment_pending')
        self.assertEqual(tx.amount, 150000)
        self.assertEqual(tx.bill_number, 'FAC-001-002-12345')

    @patch('odoo.addons.payment_bancard.models.pos_payment_method.requests.Session.request')
    def test_04_check_status_confirmed_and_receipt_data(self, mock_request):
        """Valida consulta de status (GET /v1/external/pos/venta/{txToken}) com aprovação e captura de recibo."""
        # Cria transação prévia em estado pending
        tx = self.env['bancard.pos.cajapos.transaction'].create({
            'name': 'TRN-CONFIRM-123',
            'pos_config_id': self.pos_config.id,
            'payment_method_id': self.payment_method.id,
            'pos_order_uuid': 'UUID-CONFIRM',
            'bill_number': 'FAC-001-002-9999',
            'pos_code': 'pos2342',
            'provider_id': '0001',
            'amount': 250000,
            'state': 'payment_pending',
        })

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'token': 'TRN-CONFIRM-123',
            'status': 'PAYMENT_CONFIRMED',
            'resultCode': '00',
            'description': 'APROBADO',
            'additionalInfo': {
                'bancardInfo': {
                    'responseCode': '00',
                    'responseMessage': 'APROBADO',
                    'ticketNumber': 'TICK-884422',
                    'authorizationCode': 'AUTH-771133',
                    'dateTime': '22/10/2026 14:30:00',
                    'cardLastNumbers': '4321',
                    'cardholderName': 'JUAN PEREZ',
                    'readType': 'T',
                    'deviceModel': 'T6',
                    'deviceSerial': 'SN-T6-99001',
                }
            }
        }
        mock_request.return_value = mock_response

        res = self.payment_method.bancard_cajapos_check_status(self.pos_config.id, 'TRN-CONFIRM-123')

        self.assertEqual(res['status'], 'success')
        self.assertEqual(res['payment_status'], 'PAYMENT_CONFIRMED')
        self.assertTrue(res['is_final'])
        self.assertEqual(res['ticket_number'], 'TICK-884422')
        self.assertEqual(res['authorization_code'], 'AUTH-771133')

        # Verificar atualização no registro do banco de dados
        tx.invalidate_recordset()
        self.assertEqual(tx.state, 'payment_confirmed')
        self.assertEqual(tx.ticket_number, 'TICK-884422')
        self.assertEqual(tx.authorization_code, 'AUTH-771133')
        self.assertEqual(tx.card_last_numbers, '4321')
        self.assertEqual(tx.cardholder_name, 'JUAN PEREZ')
        self.assertEqual(tx.read_type, 'T')
        self.assertEqual(tx.device_model, 'T6')
        self.assertEqual(tx.device_serial, 'SN-T6-99001')

    @patch('odoo.addons.payment_bancard.models.pos_payment_method.requests.Session.request')
    def test_05_cancellation_and_terminal_offline(self, mock_request):
        """Valida tratamento de cancelamento pelo cliente (PAYMENT_CANCELLED) e erro terminal offline (tx1020)."""
        tx = self.env['bancard.pos.cajapos.transaction'].create({
            'name': 'TRN-CANCEL-456',
            'pos_config_id': self.pos_config.id,
            'payment_method_id': self.payment_method.id,
            'pos_order_uuid': 'UUID-CANCEL',
            'bill_number': 'FAC-001-002-8888',
            'pos_code': 'pos2342',
            'provider_id': '0001',
            'amount': 50000,
            'state': 'payment_pending',
        })

        # Caso A: Cliente cancelou no terminal (PAYMENT_CANCELLED)
        mock_resp_cancel = MagicMock()
        mock_resp_cancel.status_code = 200
        mock_resp_cancel.json.return_value = {
            'token': 'TRN-CANCEL-456',
            'status': 'PAYMENT_CANCELLED',
            'resultCode': '01',
            'description': 'SE CANCELO LA OPERACION',
            'additionalInfo': {
                'bancardInfo': {
                    'responseCode': '01',
                    'responseMessage': 'SE CANCELO LA OPERACION',
                    'ticketNumber': '',
                    'authorizationCode': '',
                    'dateTime': '22/10/2026 14:35:00',
                    'cardLastNumbers': '',
                    'cardholderName': '',
                    'readType': '',
                    'deviceModel': 'T6',
                    'deviceSerial': 'SN-T6-99001',
                }
            }
        }
        mock_request.return_value = mock_resp_cancel

        res = self.payment_method.bancard_cajapos_check_status(self.pos_config.id, 'TRN-CANCEL-456')
        self.assertEqual(res['payment_status'], 'PAYMENT_CANCELLED')
        self.assertTrue(res['is_final'])
        tx.invalidate_recordset()
        self.assertEqual(tx.state, 'payment_cancelled')

        # Caso B: Terminal Offline (tx1020)
        mock_resp_offline = MagicMock()
        mock_resp_offline.status_code = 400
        mock_resp_offline.json.return_value = {
            'type': 'SYSTEM',
            'code': 'tx1020',
            'message': 'La terminal está OFFLINE; revisar conexión del dispositivo. Se cancela la operación.',
            'detail': None
        }
        mock_request.return_value = mock_resp_offline

        with self.assertRaises(ValidationError) as cm:
            self.payment_method.bancard_cajapos_create_sale({
                'pos_config_id': self.pos_config.id,
                'bill_number': 'FAC-001-OFFLINE',
                'amount': 30000,
            })
        self.assertIn('tx1020', str(cm.exception))
        self.assertIn('OFFLINE', str(cm.exception))
