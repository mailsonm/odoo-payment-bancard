# -*- coding: utf-8 -*-
import hashlib

from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install', 'payment_bancard')
class TestBancardControllers(TransactionCase):
    """Suíte TDD para os Controllers Seguros (Anti-IDOR), Tokenização (máx 5 cartões) e RBAC (Etapa 2)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.currency_pyg = cls.env.ref('base.PYG', raise_if_not_found=False) or cls.env['res.currency'].search([('name', '=', 'PYG')], limit=1)

        cls.partner_a = cls.env['res.partner'].create({
            'name': 'Cliente A (Titular)',
            'email': 'cliente.a@americana.com.py',
            'phone': '+595981111111',
        })
        cls.partner_b = cls.env['res.partner'].create({
            'name': 'Cliente B (Outro Cliente)',
            'email': 'cliente.b@americana.com.py',
            'phone': '+595981222222',
        })

        cls.user_a = cls.env['res.users'].create({
            'name': 'User Cliente A',
            'login': 'user_cliente_a_bancard',
            'email': 'cliente.a@americana.com.py',
            'partner_id': cls.partner_a.id,
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])],
        })

        cls.provider = cls.env['payment.provider'].create({
            'name': 'Bancard Controller Test',
            'code': 'bancard',
            'state': 'test',
            'company_id': cls.env.company.id,
            'bancard_public_key': 'pub_ctrl_1234567890123456789012',
            'bancard_private_key': 'priv_ctrl_123456789012345678901234567890',
        })

        cls.payment_method = cls.env['payment.method'].search([('code', '=', 'card')], limit=1)
        if not cls.payment_method:
            cls.payment_method = cls.env['payment.method'].create({
                'name': 'Card',
                'code': 'card',
                'support_tokenization': True,
                'support_refund': 'full_only',
            })

    def test_01_controller_webhook_processing(self):
        """Verifica que o controller processa o payload JSON do webhook da Bancard e retorna status=success."""
        from odoo.addons.payment_bancard.controllers.main import BancardController

        tx = self.env['payment.transaction'].create({
            'provider_id': self.provider.id,
            'payment_method_id': self.payment_method.id,
            'reference': 'FA-CTRL-WH-01',
            'amount': 120000.0,
            'currency_id': self.currency_pyg.id,
            'partner_id': self.partner_a.id,
        })
        tx.bancard_shop_process_id = tx.id

        priv = self.provider.bancard_private_key
        valid_token = hashlib.md5(
            f"{priv}{tx.bancard_shop_process_id}confirm120000.00PYG".encode('utf-8')
        ).hexdigest()

        payload = {
            'operation': {
                'token': valid_token,
                'shop_process_id': tx.bancard_shop_process_id,
                'response': 'S',
                'response_code': '00',
                'amount': '120000.00',
                'currency': 'PYG',
                'authorization_number': '554433',
                'ticket_number': '998877',
            }
        }

        ctrl = BancardController()
        res = ctrl._process_vpos_webhook_payload(self.env, payload)
        self.assertEqual(res.get('status'), 'success')
        self.assertEqual(tx.state, 'done')

    def test_02_anti_idor_saved_cards_and_register_card(self):
        """Garante que um usuário comum (partner_a) não consiga listar nem cadastrar cartões em nome de partner_b (Anti-IDOR)."""
        from odoo.addons.payment_bancard.controllers.main import BancardController

        ctrl = BancardController()
        env_user_a = self.env(user=self.user_a)

        with self.assertRaises(AccessError):
            ctrl._validate_partner_ownership(env_user_a, self.partner_b.id)

        # Para o próprio partner_a, deve permitir
        validated_partner = ctrl._validate_partner_ownership(env_user_a, self.partner_a.id)
        self.assertEqual(validated_partner.id, self.partner_a.id)

    def test_03_card_limit_max_5_cards(self):
        """Verifica o limite oficial da Bancard de no máximo 5 cartões tokenizados por cliente."""
        from odoo.addons.payment_bancard.controllers.main import BancardController

        for i in range(1, 6):
            self.env['payment.token'].create({
                'provider_id': self.provider.id,
                'payment_method_id': self.payment_method.id,
                'partner_id': self.partner_a.id,
                'provider_ref': f'card_ref_{i}',
                'payment_details': f'**** {1000 + i}',
                'bancard_alias_token': f'alias_tok_{i}',
                'bancard_card_id': i,
                'active': True,
            })

        ctrl = BancardController()
        res = ctrl._initiate_card_registration(self.env, self.provider, self.partner_a)
        self.assertEqual(res.get('status'), 'error')
        self.assertIn('5', res.get('message', ''))

    def test_04_manual_confirm_and_rollback_rbac(self):
        """Verifica que ações administrativas (manual_confirm / manual_rollback) exigem grupo gerencial/sistema."""
        from odoo.addons.payment_bancard.controllers.main import BancardController

        ctrl = BancardController()
        env_user_a = self.env(user=self.user_a)

        with self.assertRaises(AccessError):
            ctrl._check_manager_or_admin_access(env_user_a)

        # Admin deve passar
        self.assertTrue(ctrl._check_manager_or_admin_access(self.env))
