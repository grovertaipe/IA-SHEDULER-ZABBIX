<?php declare(strict_types = 1);

namespace Modules\AIMaintenance;

use Zabbix\Core\CWidget;

/**
 * AI Maintenance widget class (Req 33.3).
 *
 * Extends the native Zabbix CWidget: declares default sizing and wires assets via
 * manifest.json. i18n (Req 33.2) for the JS side is handled by a self-contained
 * catalog (assets/js/i18n.js, class AIMaintenanceI18n) that follows the Zabbix
 * user's language, because the module strings are not present in Zabbix's .mo
 * catalogs. getTranslationStrings() below is retained (harmless) for backward
 * compatibility, but the JS no longer depends on it.
 */
class Widget extends CWidget {

    public function getDefaultWidth(): int {
        return 6; // Default widget width.
    }

    public function getDefaultHeight(): int {
        return 5; // Default widget height.
    }

    /**
     * Retained for backward compatibility (Req 33.2). The JS side now resolves
     * translations through the self-contained AIMaintenanceI18n catalog
     * (assets/js/i18n.js), so this map is no longer required at runtime.
     */
    public function getTranslationStrings(): array {
        return [
            'class.widget.js' => [
                // Controls / ARIA labels
                'Send message' => _('Send message'),
                'Message to the assistant' => _('Message to the assistant'),
                'Conversation history' => _('Conversation history'),
                'View routine maintenance templates' => _('View routine maintenance templates'),
                'Confirm maintenance' => _('Confirm maintenance'),
                'Retry' => _('Retry'),
                'Retry last request' => _('Retry last request'),

                // Processing / status
                'Processing...' => _('Processing...'),
                'Analyzing request...' => _('Analyzing request...'),
                'Creating maintenance...' => _('Creating maintenance...'),
                'Retrying...' => _('Retrying...'),
                'Connection error' => _('Connection error'),

                // Health / connection
                'System reports status' => _('System reports status'),
                'Zabbix status' => _('Zabbix status'),
                'AI provider' => _('AI provider'),
                'Not available' => _('Not available'),
                'Connected' => _('Connected'),
                'Disconnected' => _('Disconnected'),
                'Some features may be limited.' => _('Some features may be limited.'),
                'System connected' => _('System connected'),
                'Features' => _('Features'),
                'Tickets' => _('Tickets'),
                'System status' => _('System status'),
                'Could not verify the connection with the backend.' => _('Could not verify the connection with the backend.'),
                'Features may be limited until the connection is restored.' => _('Features may be limited until the connection is restored.'),
                'Could not connect to the backend. Verify the service is running.' => _('Could not connect to the backend. Verify the service is running.'),
                'The request took too long. You can try again.' => _('The request took too long. You can try again.'),

                // Validation / errors
                'Error' => _('Error'),
                'No data' => _('No data'),
                'Invalid response from server' => _('Invalid response from server'),
                'The message is too short. Describe what kind of maintenance you need to create.' => _('The message is too short. Describe what kind of maintenance you need to create.'),
                'The message is too long. Please be more concise.' => _('The message is too long. Please be more concise.'),
                'I received a response I could not fully process.' => _('I received a response I could not fully process.'),
                'There is no maintenance data to confirm' => _('There is no maintenance data to confirm'),
                'There are no valid hosts or groups to create the maintenance' => _('There are no valid hosts or groups to create the maintenance'),
                'No valid hosts or groups found to create the maintenance' => _('No valid hosts or groups found to create the maintenance'),
                'Error creating maintenance' => _('Error creating maintenance'),

                // Templates
                'Templates are not available right now.' => _('Templates are not available right now.'),
                'Routine maintenance examples' => _('Routine maintenance examples'),
                'Routine maintenance templates' => _('Routine maintenance templates'),
                'Examples' => _('Examples'),
                'Detected information' => _('Detected information'),

                // Maintenance summary / preview
                'Analysis completed' => _('Analysis completed'),
                'Ticket' => _('Ticket'),
                'Type' => _('Type'),
                'Configuration' => _('Configuration'),
                'Summary' => _('Summary'),
                'Hosts found' => _('Hosts found'),
                'Groups found' => _('Groups found'),
                'Hosts by tags' => _('Hosts by tags'),
                'With ticket' => _('With ticket'),
                'Yes' => _('Yes'),
                'Routine maintenance' => _('Routine maintenance'),
                'Period' => _('Period'),
                'From' => _('From'),
                'To' => _('To'),
                'Description' => _('Description'),
                'Confidence' => _('Confidence'),
                'Servers found' => _('Servers found'),
                'Trigger tags' => _('Trigger tags'),
                'Servers NOT found' => _('Servers NOT found'),
                'Groups NOT found' => _('Groups NOT found'),
                'Maintenance details' => _('Maintenance details'),
                'Recurrence' => _('Recurrence'),
                'Technical configuration' => _('Technical configuration'),
                'Days bitmask' => _('Days bitmask'),
                'Week' => _('Week'),
                'Months' => _('Months'),
                'Day' => _('Day'),
                'of the month' => _('of the month'),
                'Servers' => _('Servers'),
                'Groups' => _('Groups'),
                'Name' => _('Name'),
                'No ticket' => _('No ticket'),
                'This maintenance repeats automatically according to the configured schedule. Review times and frequency carefully before confirming.' => _('This maintenance repeats automatically according to the configured schedule. Review times and frequency carefully before confirming.'),
                'The standard name will be used. To include a ticket in future requests, mention it in the message (e.g. "ticket 100-178306").' => _('The standard name will be used. To include a ticket in future requests, mention it in the message (e.g. "ticket 100-178306").'),

                // Recurrence labels
                'Single' => _('Single'),
                'Daily' => _('Daily'),
                'Weekly' => _('Weekly'),
                'Monthly' => _('Monthly'),
                'Every' => _('Every'),
                'day(s)' => _('day(s)'),
                'week(s)' => _('week(s)'),
                'month(s)' => _('month(s)'),
                'at' => _('at'),
                'on' => _('on'),
                'of every' => _('of every'),
                'of every month' => _('of every month'),
                'first' => _('first'),
                'second' => _('second'),
                'third' => _('third'),
                'fourth' => _('fourth'),
                'last' => _('last'),
                'week' => _('week'),
                'Custom configuration' => _('Custom configuration'),

                // Day names
                'Monday' => _('Monday'),
                'Tuesday' => _('Tuesday'),
                'Wednesday' => _('Wednesday'),
                'Thursday' => _('Thursday'),
                'Friday' => _('Friday'),
                'Saturday' => _('Saturday'),
                'Sunday' => _('Sunday'),

                // Month names
                'January' => _('January'),
                'February' => _('February'),
                'March' => _('March'),
                'April' => _('April'),
                'May' => _('May'),
                'June' => _('June'),
                'July' => _('July'),
                'August' => _('August'),
                'September' => _('September'),
                'October' => _('October'),
                'November' => _('November'),
                'December' => _('December'),
                'All months' => _('All months'),

                // Name generation
                'Routine' => _('Routine'),
                'Group' => _('Group'),
                'and' => _('and'),
                'more hosts' => _('more hosts'),
                'more groups' => _('more groups'),
                'Various resources' => _('Various resources'),

                // Maintenance list summary
                'Routine maintenance configured' => _('Routine maintenance configured'),
                'Auto-generated' => _('Auto-generated'),
                'It will run automatically according to the configuration' => _('It will run automatically according to the configuration'),
                'Maintenance summary' => _('Maintenance summary'),
                'With tickets' => _('With tickets'),
                'Total' => _('Total')
            ]
        ];
    }
}
