from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_lessonplan'),
    ]

    operations = [
        migrations.AlterField(
            model_name='logo',
            name='image',
            field=models.TextField(help_text='Base64 data-URI string of the logo image'),
        ),
    ]
