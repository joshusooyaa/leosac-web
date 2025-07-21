"""
User management routes for Flask application.
"""
import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from services.websocket_service import leosac_client
from utils.rank_converter import USER_RANKS

logger = logging.getLogger(__name__)

users_bp = Blueprint('users', __name__)

@users_bp.route('/users')
@login_required
def users_list():
    """List all users"""
    try:
        auth_state = leosac_client.get_auth_state()
        if not auth_state['connected']:
            logger.warning('WebSocket connection not available in users_list route.')
            flash('WebSocket connection not available. Please try again.', 'error')
            return render_template('users/list.html', users=[])
        users = leosac_client.get_users()
        return render_template('users/list.html', users=users)
    except Exception as e:
        logger.error(f'Error loading users: {str(e)}')
        flash(f'Error loading users: {str(e)}', 'error')
        return render_template('users/list.html', users=[])

@users_bp.route('/users/create', methods=['GET', 'POST'])
@login_required
def users_create():
    """Create a new user"""
    if request.method == 'POST':
        try:
            # Check if WebSocket client is connected
            auth_state = leosac_client.get_auth_state()
            if not auth_state['connected']:
                flash('WebSocket connection not available. Please try again.', 'error')
                return render_template('users/create.html', user_data=request.form, ranks=USER_RANKS)
            
            # Get form data
            user_data = {
                'username': request.form.get('username'),
                'firstname': request.form.get('firstname'),
                'lastname': request.form.get('lastname'),
                'email': request.form.get('email'),
                'password': request.form.get('password'),
                'rank': request.form.get('rank', 'user'),
                'validity_enabled': request.form.get('validity_enabled') == 'on',
                'validity_start': request.form.get('validity_start'),
                'validity_end': request.form.get('validity_end')
            }
            
            # Validate required fields
            if not all([user_data['username'], user_data['firstname'], 
                       user_data['lastname'], user_data['email'], user_data['password']]):
                flash('All fields are required', 'error')
                return render_template('users/create.html', user_data=user_data, ranks=USER_RANKS)
            
            # Create user via WebSocket
            success, result = leosac_client.create_user(user_data)
            
            if success:
                flash('User created successfully!', 'success')
                return redirect(url_for('users.users_list'))
            else:
                error_msg = result.get('status_string', 'Unknown error')
                flash(f'Failed to create user: {error_msg}', 'error')
                return render_template('users/create.html', user_data=user_data, ranks=USER_RANKS)
                
        except Exception as e:
            flash(f'Error creating user: {str(e)}', 'error')
            return render_template('users/create.html', user_data=request.form, ranks=USER_RANKS)
    
    # Available user ranks
    return render_template('users/create.html', ranks=USER_RANKS)

@users_bp.route('/users/delete/<int:user_id>', methods=['POST'])
@login_required
def users_delete(user_id):
    """Delete a user"""
    try:
        # Check if WebSocket client is connected
        auth_state = leosac_client.get_auth_state()
        if not auth_state['connected']:
            flash('WebSocket connection not available. Please try again.', 'error')
            return redirect(url_for('users.users_list'))
        
        # Don't allow deleting the current user
        if user_id == current_user.id:
            flash('You cannot delete your own account', 'error')
            return redirect(url_for('users.users_list'))
        
        # Delete user via WebSocket
        success, result = leosac_client.delete_user(user_id)
        
        if success:
            flash('User deleted successfully!', 'success')
        else:
            error_msg = result.get('status_string', 'Unknown error')
            flash(f'Failed to delete user: {error_msg}', 'error')
            
    except Exception as e:
        flash(f'Error deleting user: {str(e)}', 'error')
    
    return redirect(url_for('users.users_list'))

@users_bp.route('/profile/<int:user_id>')
@login_required
def profile(user_id):
    """View user profile"""
    try:
        # Check if WebSocket client is connected
        auth_state = leosac_client.get_auth_state()
        if not auth_state['connected']:
            flash('WebSocket connection not available. Please try again.', 'error')
            return redirect(url_for('users.users_list'))
        
        # Get user details from WebSocket
        user = leosac_client.get_user(user_id)
        
        if user:
            # Get additional user data
            user_groups = leosac_client.get_user_groups(user_id)
            user_credentials = leosac_client.get_user_credentials(user_id)

            # Collect group and credential IDs for indirect mapping
            group_ids = set()
            for g in user_groups:
                if g.get('group_id'):
                    group_ids.add(str(g['group_id']))
            credential_ids = set()
            for c in user_credentials:
                if c.get('id'):
                    credential_ids.add(str(c['id']))

            # Fetch all schedules (with mappings)
            all_schedules_raw = leosac_client._run_in_websocket_thread('schedule.read', {'schedule_id': 0})
            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"Raw schedules response: {all_schedules_raw}")
            user_schedules = []
            if all_schedules_raw and 'data' in all_schedules_raw:
                included_mappings = []
                if 'included' in all_schedules_raw:
                    for item in all_schedules_raw['included']:
                        if item.get('type') == 'schedule-mapping':
                            included_mappings.append(item)
                logger.info(f"Included schedule mappings: {included_mappings}")
                # Build mapping_id -> mapping object
                mapping_id_to_mapping = {str(m['id']): m for m in included_mappings}
                for schedule_data in all_schedules_raw['data']:
                    schedule_id = str(schedule_data.get('id'))
                    mapping_refs = schedule_data.get('relationships', {}).get('mapping', {}).get('data', [])
                    mappings = [mapping_id_to_mapping.get(str(ref.get('id'))) for ref in mapping_refs if mapping_id_to_mapping.get(str(ref.get('id')))]
                    logger.info(f"Checking schedule {schedule_id} ({schedule_data.get('attributes', {}).get('name')}) with mappings: {mappings}")
                    for mapping in mappings:
                        user_ids = [str(u.get('id')) for u in mapping.get('relationships', {}).get('users', {}).get('data', [])]
                        group_ids_map = [str(g.get('id')) for g in mapping.get('relationships', {}).get('groups', {}).get('data', [])]
                        cred_ids_map = [str(c.get('id')) for c in mapping.get('relationships', {}).get('credentials', {}).get('data', [])]
                        logger.info(f"Mapping {mapping.get('id')}: user_id={user_id} user_ids={user_ids} group_ids={group_ids} group_ids_map={group_ids_map} credential_ids={credential_ids} cred_ids_map={cred_ids_map}")
                        if (str(user_id) in user_ids) or (set(group_ids_map) & group_ids) or (set(cred_ids_map) & credential_ids):
                            logger.info(f"User {user_id} matched mapping {mapping.get('id')} for schedule {schedule_id}")
                            schedule = {
                                'id': schedule_data.get('id'),
                                'name': schedule_data.get('attributes', {}).get('name'),
                                'description': schedule_data.get('attributes', {}).get('description'),
                                'timeframes': schedule_data.get('attributes', {}).get('timeframes', []),
                                'version': schedule_data.get('attributes', {}).get('version', 0)
                            }
                            user_schedules.append(schedule)
                            break  # Only need to add once per schedule
                logger.info(f"User {user_id} schedules after filtering: {user_schedules}")
            
            return render_template('profile.html', 
                                 user=user, 
                                 user_groups=user_groups,
                                 user_credentials=user_credentials,
                                 user_schedules=user_schedules,
                                 ranks=USER_RANKS)
        else:
            flash('User not found', 'error')
            return redirect(url_for('users.users_list'))
            
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception(f'Error loading user profile: {str(e)}')
        flash(f'Error loading user profile: {str(e)}', 'error')
        return redirect(url_for('users.users_list'))

@users_bp.route('/profile/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
def profile_edit(user_id):
    """Edit user profile"""
    try:
        # Check if WebSocket client is connected
        auth_state = leosac_client.get_auth_state()
        if not auth_state['connected']:
            flash('WebSocket connection not available. Please try again.', 'error')
            return redirect(url_for('users.profile', user_id=user_id))
        
        # Get user details
        user = leosac_client.get_user(user_id)
        if not user:
            flash('User not found', 'error')
            return redirect(url_for('users.users_list'))
        
        if request.method == 'POST':
            # Get form data
            user_data = {
                'firstname': request.form.get('firstname'),
                'lastname': request.form.get('lastname'),
                'email': request.form.get('email'),
                'rank': request.form.get('rank', 'user'),
                'validity_enabled': request.form.get('validity_enabled') == 'on',
                'validity_start': request.form.get('validity_start'),
                'validity_end': request.form.get('validity_end')
            }
            
            # Validate required fields
            if not all([user_data['firstname'], user_data['lastname'], user_data['email']]):
                flash('First name, last name, and email are required', 'error')
                return render_template('profile_edit.html', user=user, ranks=USER_RANKS)
            
            # Update user via WebSocket
            success, result = leosac_client.update_user_profile(user_id, user_data)
            
            if success:
                flash('Profile updated successfully!', 'success')
                return redirect(url_for('users.profile', user_id=user_id))
            else:
                error_msg = result.get('status_string', 'Unknown error')
                flash(f'Failed to update profile: {error_msg}', 'error')
                return render_template('profile_edit.html', user=user, ranks=USER_RANKS)
        
        return render_template('profile_edit.html', user=user, ranks=USER_RANKS)
        
    except Exception as e:
        flash(f'Error editing profile: {str(e)}', 'error')
        return redirect(url_for('users.profile', user_id=user_id))

@users_bp.route('/profile/<int:user_id>/change-password', methods=['POST'])
@login_required
def profile_change_password(user_id):
    """Change user password"""
    try:
        # Check if WebSocket client is connected
        auth_state = leosac_client.get_auth_state()
        if not auth_state['connected']:
            flash('WebSocket connection not available. Please try again.', 'error')
            return redirect(url_for('users.profile', user_id=user_id))
        
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        new_password2 = request.form.get('new_password2')
        
        # Validate passwords
        if not new_password:
            flash('New password is required', 'error')
            return redirect(url_for('users.profile', user_id=user_id))
        
        if new_password != new_password2:
            flash('New passwords do not match', 'error')
            return redirect(url_for('users.profile', user_id=user_id))
        
        # Change password via WebSocket
        success, result = leosac_client.change_user_password(user_id, current_password, new_password)
        
        if success:
            flash('Password changed successfully!', 'success')
        else:
            error_msg = result.get('status_string', 'Unknown error')
            flash(f'Failed to change password: {error_msg}', 'error')
        
        return redirect(url_for('users.profile', user_id=user_id))
        
    except Exception as e:
        flash(f'Error changing password: {str(e)}', 'error')
        return redirect(url_for('users.profile', user_id=user_id)) 