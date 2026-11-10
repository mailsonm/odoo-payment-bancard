# -*- coding: utf-8 -*-
import hmac
import logging
import pprint

from werkzeug import urls

from odoo import _, http
from odoo.exceptions import AccessError, ValidationError
from odoo.http import request

from odoo.addons.payment_bancard import const

_logger = logging.getLogger(__name__)


class BancardController(http.Controller):
    _webhook_url = '/payment/bancard/confirm'
    _return_url = '/payment/bancard/return'
    _cancel_url = '/payment/bancard/cancel'
    _card_return_url = '/payment/bancard/card_return'

    # === Helpers de Segurança (Anti-IDOR e RBAC) ===

    @staticmethod
    def _is_manager_or_admin(env):
        user = env.user
        if (
            user._is_admin()
            or user.has_group('base.group_system')
            or user.has_group('point_of_sale.group_pos_manager')
            or user.has_group('account.group_account_manager')
        ):
            return True
        # Suporte retrocompatível a grupos gerenciais customizados caso instalados
        try:
            if (
                user.has_group('farmacia_americana_base.group_gerente_sucursal')
                or user.has_group('farmacia_americana_base.group_administrador_farmacia')
            ):
                return True
        except Exception:
            pass
        return False

    def _check_manager_or_admin_access(self, env):
        """Garante que apenas administradores ou gerentes de sucursal executem operações críticas."""
        if not self._is_manager_or_admin(env):
            raise AccessError(
                env._("Acesso negado: Esta operação requer alçada de Gerente de Sucursal ou Administrador.")
            )
        return True

    def _validate_partner_ownership(self, env, partner_id):
        """Valida que o partner_id pertence ao usuário autenticado (proteção Anti-IDOR)."""
        if not partner_id:
            return env.user.partner_id

        target_partner = env['res.partner'].sudo().browse(int(partner_id)).exists()
        if not target_partner:
            raise AccessError(env._("Contacto inválido."))

        if self._is_manager_or_admin(env):
            return target_partner

        user_partner = env.user.partner_id
        if target_partner.commercial_partner_id.id != user_partner.commercial_partner_id.id:
            _logger.warning(
                "Bancard Security: Intento de IDOR bloqueado! user=%s intentó acceder a partner_id=%s",
                env.user.id, partner_id,
            )
            raise AccessError(env._("Acceso denegado: No tiene permiso para acceder a tarjetas de otro cliente."))

        return target_partner

    def _process_vpos_webhook_payload(self, env, data):
        """Procesa el payload JSON del webhook de confirmación de Bancard vPOS 2.0."""
        if not data or 'operation' not in data:
            raise ValidationError(env._("Bancard Webhook: Payload inválido sin clave 'operation'."))

        env['payment.transaction'].sudo()._process('bancard', data)
        return {'status': 'success'}

    def _process_pos_qr_webhook_payload(self, env, data):
        """
        Procesa el callback de la API Bancard VentasQR v1.2 (envoltorio operation.payment o directo).
        Regla crítica de certificación Bancard:
        - Si la transacción está marcada como 'revert_requested' o 'reverted' (cajero canceló o expiró),
          DEBE rechazar con 'ConfirmedError' para que el switch Bancard revierta el débito del cliente.
        """
        operation = data.get('operation', data) if isinstance(data, dict) else {}
        payment = operation.get('payment', operation) if isinstance(operation, dict) else {}
        hook_alias = (payment.get('hook_alias') or '').strip()

        if not hook_alias:
            return {
                'status': 'error',
                'messages': [{
                    'level': 'error',
                    'key': 'InvalidPayloadError',
                    'description': 'Falta el campo obligatorio hook_alias',
                }],
            }, 400

        qr_tx = env['bancard.pos.qr.transaction'].sudo().search([
            ('name', '=', hook_alias),
        ], limit=1)

        if not qr_tx or qr_tx.state in ('revert_requested', 'reverted'):
            _logger.warning(
                "Bancard VentasQR Webhook rechazado (ConfirmedError) para hook_alias=%s (state=%s)",
                hook_alias, qr_tx.state if qr_tx else 'not_found',
            )
            return {
                'status': 'error',
                'messages': [{
                    'level': 'error',
                    'key': 'ConfirmedError',
                    'description': 'Transaccion revertida o inexistente en caja',
                }],
            }, 400

        # F-01: Idempotencia para reenvíos legítimos (evita re-procesamiento o doble write)
        if qr_tx.state == 'confirmed':
            _logger.info(
                "Bancard VentasQR Webhook: Transacción ya confirmada (idempotente) para hook_alias=%s",
                hook_alias,
            )
            return {
                'status': 'success',
                'messages': [{
                    'level': 'success',
                    'key': 'Confirmed',
                    'description': 'Pago ya confirmado previamente',
                }],
            }, 200

        # F-01: Apenas transacciones pendientes pueden ser confirmadas
        if qr_tx.state != 'pending':
            _logger.warning(
                "Bancard VentasQR Webhook rechazado: estado inválido (%s) para hook_alias=%s",
                qr_tx.state, hook_alias,
            )
            return {
                'status': 'error',
                'messages': [{
                    'level': 'error',
                    'key': 'InvalidStateError',
                    'description': 'Transaccion en estado no confirmable',
                }],
            }, 400

        # F-01: Validación de monto enviado contra el valor esperado en la transacción
        webhook_amount = payment.get('amount')
        if webhook_amount is not None:
            try:
                webhook_amount_val = int(float(webhook_amount))
                if webhook_amount_val != qr_tx.amount:
                    _logger.warning(
                        "Bancard VentasQR Webhook rechazado: divergencia de monto para hook_alias=%s (esperado=%s, recibido=%s)",
                        hook_alias, qr_tx.amount, webhook_amount_val,
                    )
                    return {
                        'status': 'error',
                        'messages': [{
                            'level': 'error',
                            'key': 'AmountMismatchError',
                            'description': 'Monto divergente del registrado en caja',
                        }],
                    }, 400
            except (ValueError, TypeError):
                pass

        auth_number = str(payment.get('authorization_number') or '')
        ticket_number = str(payment.get('ticket_number') or '')

        qr_tx.write({
            'state': 'confirmed',
            'authorization_number': auth_number,
            'ticket_number': ticket_number,
            'response_payload': pprint.pformat(data),
        })

        # Notifica instantáneamente al PDV vía WebSocket nativo de Odoo 19
        if qr_tx.pos_config_id:
            try:
                qr_tx.pos_config_id._notify('BANCARD_QR_PAYMENT_STATUS', {
                    'config_id': qr_tx.pos_config_id.id,
                    'hook_alias': hook_alias,
                    'state': 'confirmed',
                    'authorization_number': auth_number,
                    'ticket_number': ticket_number,
                    'pos_order_uuid': qr_tx.pos_order_uuid,
                })
            except Exception as notify_err:
                _logger.warning("Bancard VentasQR fallo no bloqueante en _notify WS: %s", notify_err)

        return {
            'status': 'success',
            'messages': [{
                'level': 'success',
                'key': 'Confirmed',
                'description': 'Pago recibido con exito',
            }],
        }, 200

    def _initiate_card_registration(self, env, provider, partner):
        """Inicia el flujo de registro de tarjeta (cards/new) respetando el límite oficial de 5 tarjetas."""
        provider_sudo = provider.sudo()
        existing_count = env['payment.token'].sudo().search_count([
            ('provider_id', '=', provider_sudo.id),
            ('partner_id', '=', partner.id),
            ('active', '=', True),
        ])
        if existing_count >= 5:
            return {
                'status': 'error',
                'message': env._("Límite alcanzado: Ya posee el máximo de 5 tarjetas registradas en Bancard."),
            }

        last_token = env['payment.token'].sudo().search(
            [('provider_id', '=', provider_sudo.id), ('bancard_card_id', '!=', False)],
            order='bancard_card_id desc',
            limit=1,
        )
        next_card_id = (last_token.bancard_card_id or 0) + 1
        user_id = partner.id

        md5_token = provider_sudo._bancard_generate_token(
            'cards_new',
            card_id=next_card_id,
            user_id=user_id,
        )

        base_url = provider_sudo.get_base_url()
        return_url = urls.url_join(
            base_url,
            f"{self._card_return_url}?partner_id={user_id}&card_id={next_card_id}&provider_id={provider_sudo.id}",
        )

        payload = {
            'public_key': provider_sudo.bancard_public_key,
            'operation': {
                'token': md5_token,
                'card_id': next_card_id,
                'user_id': user_id,
                'user_cell_phone': partner.phone or '0981000000',
                'user_mail': partner.email or (request.env.company.email or 'cliente@ejemplo.com.py'),
                'return_url': return_url,
            },
        }

        result = provider_sudo._bancard_make_request(
            const.BANCARD_ENDPOINTS['cards_new'],
            payload,
        )

        return {
            'status': 'success',
            'process_id': result.get('process_id'),
            'card_id': next_card_id,
            'checkout_js_url': provider_sudo._bancard_get_checkout_js_url(),
            'iframe_styles': provider_sudo._bancard_get_iframe_styles(),
        }

    # === Rotas HTTP / JSON-RPC (Odoo 19) ===

    @http.route(_webhook_url, type='http', auth='public', methods=['POST'], csrf=False)
    def bancard_webhook(self):
        """Recebe o POST JSON da Bancard (Single Buy / Charge Confirmation)."""
        try:
            data = request.get_json_data()
        except Exception:
            data = None

        _logger.info("Bancard vPOS Webhook recibido:\n%s", pprint.pformat(data))

        if not data:
            return request.make_json_response(
                {'status': 'error', 'message': 'Invalid JSON payload'},
                status=400,
            )

        try:
            res = self._process_vpos_webhook_payload(request.env, data)
            return request.make_json_response(res, status=200)
        except ValidationError as err:
            _logger.error("Bancard vPOS Webhook error de validación: %s", err)
            return request.make_json_response(
                {'status': 'error', 'message': str(err)},
                status=400,
            )
        except Exception as err:
            _logger.exception("Bancard vPOS Webhook error inesperado: %s", err)
            return request.make_json_response(
                {'status': 'error', 'message': 'Internal server error'},
                status=500,
            )

    @http.route('/payment/bancard/qr_webhook', type='http', auth='public', methods=['POST'], csrf=False)
    def bancard_qr_webhook(self):
        """Webhook oficial de confirmación de la API Bancard VentasQR v1.2 (tiempo de respuesta <= 5s)."""
        # F-01: Si está configurado secret token en el sistema, validar autenticidad
        qr_secret = request.env['ir.config_parameter'].sudo().get_param('bancard.qr_webhook_secret')
        if qr_secret:
            incoming_token = (
                request.params.get('token')
                or request.headers.get('X-Bancard-Token')
                or request.headers.get('Authorization')
            )
            if not incoming_token or not hmac.compare_digest(str(incoming_token).strip(), str(qr_secret).strip()):
                _logger.warning("Bancard VentasQR Webhook: intento de acceso no autorizado (token ausente o inválido)")
                return request.make_json_response({
                    'status': 'error',
                    'messages': [{'level': 'error', 'key': 'Unauthorized', 'description': 'Token de autorizacion invalido'}],
                }, status=401)

        try:
            data = request.get_json_data()
        except Exception:
            data = None

        _logger.info("Bancard VentasQR Webhook recibido:\n%s", pprint.pformat(data))
        if not data:
            return request.make_json_response({
                'status': 'error',
                'messages': [{'level': 'error', 'key': 'InvalidJson', 'description': 'JSON invalido'}],
            }, status=400)

        response_dict, http_status = self._process_pos_qr_webhook_payload(request.env, data)
        return request.make_json_response(response_dict, status=http_status)

    @http.route(_return_url, type='http', auth='public', methods=['GET', 'POST'], csrf=False)
    def bancard_return(self, **params):
        """Redirección del navegador tras conclusión en el iframe Bancard."""
        shop_process_id = params.get('shop_process_id')
        if shop_process_id:
            try:
                sp_id = int(shop_process_id)
            except (ValueError, TypeError):
                sp_id = False
            if sp_id:
                tx_sudo = request.env['payment.transaction'].sudo().search([
                    ('bancard_shop_process_id', '=', sp_id),
                    ('provider_code', '=', 'bancard'),
                ], limit=1)
                if tx_sudo and tx_sudo.state in ('draft', 'pending'):
                    try:
                        tx_sudo._bancard_get_confirmation()
                    except Exception as err:
                        _logger.warning("Bancard return: fallo al consultar confirmación: %s", err)
        return request.redirect('/payment/status')

    @http.route(_cancel_url, type='http', auth='public', methods=['GET', 'POST'], csrf=False)
    def bancard_cancel(self, **params):
        """Redirección cuando el cliente cancela el checkout en el iframe Bancard."""
        shop_process_id = params.get('shop_process_id')
        if shop_process_id:
            try:
                sp_id = int(shop_process_id)
            except (ValueError, TypeError):
                sp_id = False
            if sp_id:
                tx_sudo = request.env['payment.transaction'].sudo().search([
                    ('bancard_shop_process_id', '=', sp_id),
                    ('provider_code', '=', 'bancard'),
                ], limit=1)
                if tx_sudo and tx_sudo.state in ('draft', 'pending'):
                    tx_sudo._set_canceled(state_message=_("Pago cancelado por el usuario."))
        return request.redirect('/payment/status')

    @http.route('/payment/bancard/register_card', type='jsonrpc', auth='user', methods=['POST'])
    def bancard_register_card(self, provider_id, partner_id=None):
        """Inicia el registro de una nueva tarjeta tokenizada para el cliente autenticado."""
        try:
            partner = self._validate_partner_ownership(request.env, partner_id)
            provider = request.env['payment.provider'].sudo().browse(int(provider_id)).exists()
            if not provider or provider.code != 'bancard':
                return {'status': 'error', 'message': _('Proveedor Bancard no encontrado.')}
            return self._initiate_card_registration(request.env, provider, partner)
        except (AccessError, ValidationError) as err:
            return {'status': 'error', 'message': str(err)}

    @http.route(_card_return_url, type='http', auth='user', methods=['GET', 'POST'], csrf=False)
    def bancard_card_return(self, **params):
        """Retorno tras registro de tarjeta en el iframe Bancard (sincroniza users_cards)."""
        partner_id = params.get('partner_id')
        provider_id = params.get('provider_id')
        status = params.get('status')

        if status == 'add_new_card_fail':
            return request.redirect('/my/payment_method')

        if partner_id and provider_id:
            try:
                partner = self._validate_partner_ownership(request.env, partner_id)
                provider = request.env['payment.provider'].sudo().browse(int(provider_id)).exists()
                if provider and provider.code == 'bancard':
                    self._sync_user_cards(provider, partner)
            except Exception as err:
                _logger.error("Bancard: Error al sincronizar tarjetas: %s", err)

        return request.redirect('/my/payment_method')

    @http.route('/payment/bancard/saved_cards', type='jsonrpc', auth='user', methods=['POST'])
    def bancard_saved_cards(self, provider_id, partner_id=None):
        """Lista las tarjetas tokenizadas en Bancard para el cliente autenticado (Anti-IDOR)."""
        try:
            partner = self._validate_partner_ownership(request.env, partner_id)
            provider = request.env['payment.provider'].sudo().browse(int(provider_id)).exists()
            if not provider or provider.code != 'bancard':
                return {'status': 'error', 'cards': []}
            cards = self._sync_user_cards(provider, partner)
            return {'status': 'success', 'cards': cards}
        except (AccessError, ValidationError) as err:
            return {'status': 'error', 'message': str(err), 'cards': []}

    @http.route('/payment/bancard/charge_token', type='jsonrpc', auth='user', methods=['POST'])
    def bancard_charge_token(self, transaction_id, token_id, number_of_payments=1):
        """Ejecuta cobro 1-Click / 3DS usando una tarjeta tokenizada del propio cliente."""
        try:
            tx_sudo = request.env['payment.transaction'].sudo().browse(int(transaction_id)).exists()
            token_sudo = request.env['payment.token'].sudo().browse(int(token_id)).exists()
            if not tx_sudo or not token_sudo:
                return {'status': 'error', 'message': _('Transacción o tarjeta no encontrada.')}

            # Validación Anti-IDOR sobre el titular de la transacción y del token
            self._validate_partner_ownership(request.env, tx_sudo.partner_id.id)
            self._validate_partner_ownership(request.env, token_sudo.partner_id.id)

            result = tx_sudo._bancard_charge_with_token(
                alias_token=token_sudo.bancard_alias_token,
                number_of_payments=int(number_of_payments or 1),
            )
            return {
                'status': 'success',
                'state': tx_sudo.state,
                'process_id': tx_sudo.bancard_process_id,
                'result': result,
            }
        except (AccessError, ValidationError) as err:
            return {'status': 'error', 'message': str(err)}

    @http.route('/payment/bancard/manual_confirm', type='jsonrpc', auth='user', methods=['POST'])
    def bancard_manual_confirm(self, transaction_id):
        """Consulta manual de confirmación en Bancard (restringido a gerentes/administradores)."""
        self._check_manager_or_admin_access(request.env)
        tx_sudo = request.env['payment.transaction'].sudo().browse(int(transaction_id)).exists()
        if not tx_sudo or tx_sudo.provider_code != 'bancard':
            return {'status': 'error', 'message': _('Transacción Bancard no encontrada.')}
        try:
            result = tx_sudo._bancard_get_confirmation()
            return {'status': 'success', 'state': tx_sudo.state, 'result': result}
        except ValidationError as err:
            return {'status': 'error', 'message': str(err)}

    @http.route('/payment/bancard/manual_rollback', type='jsonrpc', auth='user', methods=['POST'])
    def bancard_manual_rollback(self, transaction_id):
        """Rollback manual en Bancard (restringido a gerentes/administradores)."""
        self._check_manager_or_admin_access(request.env)
        tx_sudo = request.env['payment.transaction'].sudo().browse(int(transaction_id)).exists()
        if not tx_sudo or tx_sudo.provider_code != 'bancard':
            return {'status': 'error', 'message': _('Transacción Bancard no encontrada.')}
        try:
            result = tx_sudo._bancard_rollback()
            return {'status': 'success', 'state': tx_sudo.state, 'result': result}
        except ValidationError as err:
            return {'status': 'error', 'message': str(err)}

    def _sync_user_cards(self, provider, partner):
        """Sincroniza las tarjetas del contacto vía endpoint oficial /vpos/api/0.3/users/{id}/cards."""
        provider_sudo = provider.sudo()
        user_id = partner.id
        md5_token = provider_sudo._bancard_generate_token('users_cards', user_id=user_id)
        endpoint = const.BANCARD_ENDPOINTS['users_cards'].format(user_id=user_id)
        payload = {
            'public_key': provider_sudo.bancard_public_key,
            'operation': {
                'token': md5_token,
            },
        }

        result = provider_sudo._bancard_make_request(endpoint, payload)
        cards = result.get('cards', [])
        pm_card = request.env['payment.method'].sudo().search([('code', '=', 'card')], limit=1)

        for card_data in cards:
            alias_token = card_data.get('alias_token')
            masked_number = card_data.get('card_masked_number', '')
            card_id = card_data.get('card_id')

            existing = request.env['payment.token'].sudo().search([
                ('provider_id', '=', provider_sudo.id),
                ('partner_id', '=', partner.id),
                '|',
                ('bancard_card_id', '=', card_id),
                ('bancard_card_masked_number', '=', masked_number),
            ], limit=1)

            vals = {
                'bancard_alias_token': alias_token,
                'bancard_card_masked_number': masked_number,
                'bancard_card_expiration_date': card_data.get('expiration_date', ''),
                'bancard_card_brand': card_data.get('card_brand', ''),
                'bancard_card_type': card_data.get('card_type', 'credit'),
                'bancard_card_id': card_id,
            }
            if existing:
                existing.write(vals)
            elif pm_card:
                vals.update({
                    'provider_id': provider_sudo.id,
                    'payment_method_id': pm_card.id,
                    'partner_id': partner.id,
                    'provider_ref': str(card_id or alias_token),
                    'payment_details': f"{card_data.get('card_brand', 'Card')} {masked_number}",
                })
                request.env['payment.token'].sudo().create(vals)

        return cards
