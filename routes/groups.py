from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required
from services.websocket_service import leosac_client
import logging
import traceback

groups_bp = Blueprint('groups', __name__)
logger = logging.getLogger(__name__)

def get_group_memberships_full(group_id):
    logger.info(f'Fetching all users to determine memberships for group {group_id}')
    users = leosac_client.get_users()
    logger.info(f'Raw users from API: {users}')
    memberships = []
    for user in users:
        user_memberships = user.get('relationships', {}).get('memberships', {}).get('data', [])
        if user_memberships is None:
            user_memberships = []
        for m in user_memberships:
            try:
                membership = leosac_client.get_membership(m['id'])
                logger.info(f'Membership {m["id"]} details: {membership}')
                if membership and membership.get('group_id') == group_id:
                    memberships.append({
                        'user_id': user['id'],
                        'username': user['username'],
                        'firstname': user.get('firstname', ''),
                        'lastname': user.get('lastname', ''),
                        'membership_id': membership['id'],
                        'rank': membership.get('rank'),
                        'timestamp': membership.get('timestamp'),
                    })
            except Exception as e:
                logger.error(f'Error fetching membership {m["id"]}: {e}')
    logger.info(f'Final memberships for group {group_id}: {memberships}')
    return memberships

def get_all_users_for_selection():
    """Get all users for dropdown selection, excluding those already in the group"""
    logger.info('Fetching all users for selection')
    users = leosac_client.get_users()
    logger.info(f'All users for selection: {users}')
    return users

@groups_bp.route('/groups')
@login_required
def groups_list():
    try:
        logger.info('--- groups_list called ---')
        auth_state = leosac_client.get_auth_state()
        logger.info(f'Auth state: {auth_state}')
        if not auth_state['connected']:
            logger.warning('WebSocket connection not available in groups_list route.')
            flash('WebSocket connection not available. Please try again.', 'error')
            return redirect(url_for('index'))
        groups = leosac_client.get_groups()
        logger.info(f'Raw groups from API: {groups}')
        for group in groups:
            group['member_count'] = len(get_group_memberships_full(group['id']))
        logger.info(f'Final groups for template: {groups}')
        return render_template('groups/list.html', groups=groups)
    except Exception as e:
        logger.error(f'Error loading groups: {str(e)}')
        logger.error(f'Traceback: {traceback.format_exc()}')
        flash('Error loading groups. Please try again.', 'error')
        return redirect(url_for('index'))

@groups_bp.route('/groups/<int:group_id>')
@login_required
def group_detail(group_id):
    try:
        logger.info(f'--- group_detail called for group_id={group_id} ---')
        auth_state = leosac_client.get_auth_state()
        if not auth_state['connected']:
            flash('WebSocket connection not available. Please try again.', 'error')
            return redirect(url_for('groups.groups_list'))
        group = leosac_client.get_group(group_id)
        logger.info(f'Raw group from API: {group}')
        if not group:
            flash('Group not found.', 'error')
            return redirect(url_for('groups.groups_list'))
        memberships = get_group_memberships_full(group_id)
        group['memberships'] = memberships
        # Schedules: always use get_group_schedules for reliability
        group_schedules = leosac_client.get_group_schedules(group_id)
        group['schedules'] = [
            {
                'id': sched['id'],
                'name': sched.get('name', ''),
                'description': sched.get('description', '')
            }
            for sched in group_schedules
        ]
        logger.info(f'Group {group_id} schedules: {group["schedules"]}')
        logger.info(f'Final group for template: {group}')
        return render_template('groups/detail.html', group=group)
    except Exception as e:
        logger.error(f'Error loading group detail: {str(e)}')
        logger.error(f'Traceback: {traceback.format_exc()}')
        flash('Error loading group detail. Please try again.', 'error')
        return redirect(url_for('groups.groups_list'))

@groups_bp.route('/groups/create', methods=['GET', 'POST'])
@login_required
def groups_create():
    if request.method == 'POST':
        try:
            auth_state = leosac_client.get_auth_state()
            if not auth_state['connected']:
                flash('WebSocket connection not available. Please try again.', 'error')
                return redirect(url_for('groups.groups_list'))
            name = request.form.get('name', '').strip()
            description = request.form.get('description', '').strip()
            if not name:
                flash('Group name is required.', 'error')
                return render_template('groups/create.html')
            if len(name) < 3:
                flash('Group name must be at least 3 characters long.', 'error')
                return render_template('groups/create.html')
            if len(name) > 50:
                flash('Group name must be no more than 50 characters long.', 'error')
                return render_template('groups/create.html')
            group_data = {
                'name': name,
                'description': description
            }
            success, result = leosac_client.create_group(group_data)
            if success:
                flash('Group created successfully!', 'success')
                return redirect(url_for('groups.group_detail', group_id=result['id']))
            else:
                error_msg = result.get('error', 'Unknown error occurred')
                flash(f'Failed to create group: {error_msg}', 'error')
                return render_template('groups/create.html')
        except Exception as e:
            flash('Error creating group. Please try again.', 'error')
            return render_template('groups/create.html')
    return render_template('groups/create.html')

@groups_bp.route('/groups/<int:group_id>/edit', methods=['GET', 'POST'])
@login_required
def group_edit(group_id):
    try:
        auth_state = leosac_client.get_auth_state()
        if not auth_state['connected']:
            flash('WebSocket connection not available. Please try again.', 'error')
            return redirect(url_for('groups.groups_list'))
        group = leosac_client.get_group(group_id)
        if not group:
            flash('Group not found.', 'error')
            return redirect(url_for('groups.groups_list'))
        # Get all users for add user dropdown
        all_users = get_all_users_for_selection()
        memberships = get_group_memberships_full(group_id)
        group['memberships'] = memberships
        
        # Get current schedules for this group
        group_schedules = leosac_client.get_group_schedules(group_id)
        group['schedules'] = [
            {
                'id': sched['id'],
                'name': sched.get('name', ''),
                'description': sched.get('description', '')
            }
            for sched in group_schedules
        ]
        
        # Get all schedules for dropdown
        all_schedules = leosac_client.get_schedules()
        
        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            description = request.form.get('description', '').strip()
            members_raw = request.form.getlist('members[]')
            schedules_raw = request.form.getlist('schedules[]')
            
            # Parse members: each entry is user_id:rank
            new_members = []
            for m in members_raw:
                try:
                    user_id, rank = m.split(':')
                    new_members.append({'user_id': int(user_id), 'rank': int(rank)})
                except Exception as e:
                    continue
            
            # Parse schedules: each entry is schedule_id
            new_schedules = []
            for s in schedules_raw:
                try:
                    new_schedules.append(int(s))
                except Exception as e:
                    continue
            
            # Update group info
            if not name:
                flash('Group name is required.', 'error')
                return render_template('groups/edit.html', group=group, all_users=all_users, all_schedules=all_schedules)
            if len(name) < 3:
                flash('Group name must be at least 3 characters long.', 'error')
                return render_template('groups/edit.html', group=group, all_users=all_users, all_schedules=all_schedules)
            if len(name) > 50:
                flash('Group name must be no more than 50 characters long.', 'error')
                return render_template('groups/edit.html', group=group, all_users=all_users, all_schedules=all_schedules)
            
            group_data = {
                'name': name,
                'description': description
            }
            success, result = leosac_client.update_group(group_id, group_data)
            if not success:
                error_msg = result.get('error', 'Unknown error occurred')
                flash(f'Failed to update group: {error_msg}', 'error')
                return render_template('groups/edit.html', group=group, all_users=all_users, all_schedules=all_schedules)
            
            # Update memberships: remove all, then add new
            # Get current memberships from backend
            current_memberships = get_group_memberships_full(group_id)
            current_user_ids = set(m['user_id'] for m in current_memberships)
            new_user_ids = set(m['user_id'] for m in new_members)
            # Remove users not in new list
            for m in current_memberships:
                if m['user_id'] not in new_user_ids:
                    leosac_client.delete_membership(m['membership_id'])
            # Add users not already present
            for m in new_members:
                if m['user_id'] not in current_user_ids:
                    leosac_client.create_membership(m['user_id'], group_id, m['rank'])
            
            # Update schedule mappings
            current_schedule_ids = set(s['id'] for s in group['schedules'])
            new_schedule_ids = set(new_schedules)
            
            # Remove schedules not in new list
            for schedule_id in current_schedule_ids:
                if schedule_id not in new_schedule_ids:
                    leosac_client.unmap_schedule_from_group(schedule_id, group_id)
            
            # Add schedules not already present
            for schedule_id in new_schedule_ids:
                if schedule_id not in current_schedule_ids:
                    leosac_client.map_schedule_to_group(schedule_id, group_id)
            
            flash('Group updated successfully!', 'success')
            return redirect(url_for('groups.group_detail', group_id=group_id))
        
        return render_template('groups/edit.html', group=group, all_users=all_users, all_schedules=all_schedules)
    except Exception as e:
        flash('Error editing group. Please try again.', 'error')
        return redirect(url_for('groups.groups_list'))

@groups_bp.route('/groups/<int:group_id>/delete', methods=['POST'])
@login_required
def group_delete(group_id):
    try:
        auth_state = leosac_client.get_auth_state()
        if not auth_state['connected']:
            flash('WebSocket connection not available. Please try again.', 'error')
            return redirect(url_for('groups.groups_list'))
        success, result = leosac_client.delete_group(group_id)
        if success:
            flash('Group deleted successfully!', 'success')
        else:
            error_msg = result.get('error', 'Unknown error occurred')
            flash(f'Failed to delete group: {error_msg}', 'error')
        return redirect(url_for('groups.groups_list'))
    except Exception as e:
        flash('Error deleting group. Please try again.', 'error')
        return redirect(url_for('groups.groups_list'))

@groups_bp.route('/groups/<int:group_id>/add_user', methods=['POST'])
@login_required
def group_add_user(group_id):
    try:
        user_id = int(request.form.get('user_id'))
        rank = int(request.form.get('rank', 0))
        logger.info(f'Adding user {user_id} to group {group_id} with rank {rank}')
        success, result = leosac_client.create_membership(user_id, group_id, rank)
        logger.info(f'Add user result: {success}, {result}')
        if success:
            flash('User added to group successfully!', 'success')
        else:
            flash(f'Failed to add user: {result.get("error", "Unknown error")}', 'error')
        return redirect(url_for('groups.group_detail', group_id=group_id))
    except Exception as e:
        logger.error(f'Error adding user to group: {str(e)}')
        flash('Error adding user to group.', 'error')
        return redirect(url_for('groups.group_detail', group_id=group_id))

@groups_bp.route('/groups/<int:group_id>/remove_user/<int:membership_id>', methods=['POST'])
@login_required
def group_remove_user(group_id, membership_id):
    try:
        logger.info(f'Removing membership {membership_id} from group {group_id}')
        success, result = leosac_client.delete_membership(membership_id)
        logger.info(f'Remove user result: {success}, {result}')
        if success:
            flash('User removed from group successfully!', 'success')
        else:
            flash(f'Failed to remove user: {result.get("error", "Unknown error")}', 'error')
        return redirect(url_for('groups.group_detail', group_id=group_id))
    except Exception as e:
        logger.error(f'Error removing user from group: {str(e)}')
        flash('Error removing user from group.', 'error')
        return redirect(url_for('groups.group_detail', group_id=group_id))

@groups_bp.route('/groups/<int:group_id>/add_schedule', methods=['POST'])
@login_required
def group_add_schedule(group_id):
    try:
        schedule_id = int(request.form.get('schedule_id'))
        logger.info(f'Adding schedule {schedule_id} to group {group_id}')
        success, result = leosac_client.map_schedule_to_group(schedule_id, group_id)
        logger.info(f'Add schedule result: {success}, {result}')
        if success:
            flash('Schedule mapped to group successfully!', 'success')
        else:
            flash(f'Failed to map schedule: {result.get("error", "Unknown error")}', 'error')
        return redirect(url_for('groups.group_detail', group_id=group_id))
    except Exception as e:
        logger.error(f'Error mapping schedule to group: {str(e)}')
        flash('Error mapping schedule to group.', 'error')
        return redirect(url_for('groups.group_detail', group_id=group_id))

@groups_bp.route('/groups/<int:group_id>/remove_schedule/<int:schedule_id>', methods=['POST'])
@login_required
def group_remove_schedule(group_id, schedule_id):
    try:
        logger.info(f'Removing schedule {schedule_id} from group {group_id}')
        success, result = leosac_client.unmap_schedule_from_group(schedule_id, group_id)
        logger.info(f'Remove schedule result: {success}, {result}')
        if success:
            flash('Schedule unmapped from group successfully!', 'success')
        else:
            flash(f'Failed to unmap schedule: {result.get("error", "Unknown error")}', 'error')
        return redirect(url_for('groups.group_detail', group_id=group_id))
    except Exception as e:
        logger.error(f'Error unmapping schedule from group: {str(e)}')
        flash('Error unmapping schedule from group.', 'error')
        return redirect(url_for('groups.group_detail', group_id=group_id)) 