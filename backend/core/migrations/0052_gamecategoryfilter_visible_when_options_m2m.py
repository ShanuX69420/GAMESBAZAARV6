from django.db import migrations, models


def fk_to_m2m(apps, schema_editor):
    GameCategoryFilter = apps.get_model('core', 'GameCategoryFilter')
    for gcf in GameCategoryFilter.objects.exclude(visible_when_option__isnull=True):
        gcf.visible_when_options.add(gcf.visible_when_option_id)


def m2m_to_fk(apps, schema_editor):
    GameCategoryFilter = apps.get_model('core', 'GameCategoryFilter')
    for gcf in GameCategoryFilter.objects.all():
        first = gcf.visible_when_options.order_by('pk').first()
        if first is not None:
            gcf.visible_when_option_id = first.pk
            gcf.save(update_fields=['visible_when_option'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0051_gamecategoryfilter_visible_when_option'),
    ]

    operations = [
        migrations.AddField(
            model_name='gamecategoryfilter',
            name='visible_when_options',
            field=models.ManyToManyField(
                blank=True,
                help_text='Only show this filter after the buyer/seller picks ANY of '
                          'these options on another filter in the same category (e.g., '
                          'show "Region — Gift/Account" when Method = As a Gift OR By '
                          'logging into account). Leave empty to always show this filter.',
                related_name='dependent_filter_assignments_m2m',
                to='core.filteroption',
            ),
        ),
        migrations.RunPython(fk_to_m2m, m2m_to_fk),
        migrations.RemoveField(
            model_name='gamecategoryfilter',
            name='visible_when_option',
        ),
        migrations.AlterField(
            model_name='gamecategoryfilter',
            name='visible_when_options',
            field=models.ManyToManyField(
                blank=True,
                help_text='Only show this filter after the buyer/seller picks ANY of '
                          'these options on another filter in the same category (e.g., '
                          'show "Region — Gift/Account" when Method = As a Gift OR By '
                          'logging into account). Leave empty to always show this filter.',
                related_name='dependent_filter_assignments',
                to='core.filteroption',
            ),
        ),
    ]
