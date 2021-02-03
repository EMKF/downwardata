import io
import os
import boto3
import joblib
import zipfile
import requests
import numpy as np
import pandas as pd
import kauffman_data.constants as c

pd.set_option('max_columns', 1000)
pd.set_option('max_info_columns', 1000)
pd.set_option('expand_frame_repr', False)
pd.set_option('display.max_rows', 30000)
pd.set_option('max_colwidth', 4000)
pd.set_option('display.float_format', lambda x: '%.3f' % x)



def to_s3(file, s3_bucket, s3_file):
    """
    Upload a local file to S3.

    file: str
        location of the local file
    s3_bucket: str
        Name of the S3 bucket. E.g., 'emkf.data.research'
    s3_file: str
        Destination file location in S3. E.g., 'indicators/nej/data_outputs/your_pickle_filename.pkl'

    Examples:
        from kauffman_data import data_manager as dm
        dm.from_s3('local_file_path.csv', 'emkf.data.research', 'indicators/nej/data_outputs/remote_file_path.csv')
    """
    # buf = io.BytesIO()
    # joblib.dump(df, buf)
    # s3 = boto3.client('s3')
    # s3.upload_fileobj(buf, bucket, key)  # I could not get this to work...tear. It won't write to s3; it is something about this type of object not haveing a read function.

    s3 = boto3.client('s3')
    with open(file, "rb") as f:
        s3.upload_fileobj(f, s3_bucket, s3_file)


def from_s3(file, bucket, key):
    """
    Download a file locally from S3.

    file: str
        Local file destination
    s3_bucket: str
        Name of the S3 bucket where file is located. E.g., 'emkf.data.research'
    s3_file: str
        File location in S3. E.g., 'indicators/nej/data_outputs/your_pickle_filename.pkl'

    Examples:
        from kauffman_data import data_manager
        dm.from_s3('local_file_path.csv', 'emkf.data.research', 'indicators/nej/data_outputs/remote_file_path.csv')
    """
    s3 = boto3.client('s3')
    s3.download_fileobj(bucket, key, file)


def to_s3_joblib(file_obj, s3_bucket, s3_file):
    """
    Send object to S3 as a joblib pickled (serialized) object.

    file_obj: python object
        Python object, such as a dataframe, to serialize and store in S3.

    s3_bucket: str
        Name of the S3 bucket where the file is to be located. E.g., 'emkf.data.research'

    s3_file: str
        Destination file location in S3. E.g., 'indicators/nej/data_outputs/your_pickle_filename.pkl'

    Examples:
        import numpy as np
        import pandas as pd
        from kauffman_data import data_manager as dm
        df = pd.DataFrame(np.random.uniform(0, 1, size=(10, 3)))
        dm.to_s3_joblib(df, 'emkf.data.research', 'indicators/nej/data_outputs/remote_file_path.pkl')

    """
    s3 = boto3.client('s3')
    joblib.dump(file_obj, '_joblib_temp.pkl')
    with open('_joblib_temp.pkl', "rb") as f:
        s3.upload_fileobj(f, s3_bucket, s3_file)
    os.remove('_joblib_temp.pkl')


def from_s3_joblib(s3_bucket, s3_key):
    """
    Fetch serialized object from S3 and return unserialized.

    s3_bucket: str
        Name of the S3 bucket where the file is located. E.g., 'emkf.data.research'

    s3_file: str
        File location in S3. E.g., 'indicators/nej/data_outputs/your_pickle_filename.pkl'

    Examples:
        from kauffman_data import data_manager as dm
        df = dm.from_s3_joblib('emkf.data.research', 'indicators/nej/data_outputs/remote_file_path.pkl')

    """
    buf = io.BytesIO()
    s3 = boto3.client('s3')
    s3.download_fileobj(s3_bucket, s3_key, buf)
    return joblib.load(buf)


# do we want to include this? maybe
def weighted_crosstab(df, var1, var2, weight):
    # print(df.head())
    print(pd.crosstab(df['Q10'], df['Q4']))
    # print(pd.crosstab(df['Q10'], df['Q4'], values=1, aggfunc='sum'))
    print(pd.crosstab(df['Q10'], df['Q4'], values=df['WEIGHT'], aggfunc='sum'))



def zip_to_dataframe(url):
    """
    Takes a url and reads in the .dat file. Assumes only one file inside the zip and that it is .dat formatted.

    TODO: generalize this.
    """
    r = requests.get(url)
    filebytes = io.BytesIO(r.content)
    myzipfile = zipfile.ZipFile(filebytes)
    for name in myzipfile.namelist():
        return pd.read_csv(myzipfile.open(name), sep='|', low_memory=False)


def _region_transform(df, v, df_out):
    covar_lst = [col for col in df.columns.tolist() if v + '_' in col and col.count('_') == 1]
    new_covar_lst = [col.replace('_', '') for col in covar_lst]
    df_v = df.\
        rename(columns={**dict(zip(covar_lst, new_covar_lst)), **{'sname': 'name', 'demtype': 'type', 'demographic': 'category'}}). \
        replace('Annual', 'Total').\
        assign(
            type=lambda x: 'Total' if 'type' not in x.columns else x['type'],
            category=lambda x: 'Total' if 'category' not in x.columns else x['category'],
            fips=lambda x: x['name'].map(c.us_state_abbrev).map(c.state_abb_fips_dic)
            # fips=lambda x: x['name'].map(c.us_state_abbrev).map(c.state_dic_temp)
        ) \
        [['name', 'fips', 'type', 'category'] + new_covar_lst].\
        query('category != "Ages 25-64"'). \
        pipe(pd.wide_to_long, v, i=['name', 'fips', 'type', 'category'], j='year'). \
        reset_index(). \
        assign(category=lambda x: pd.Categorical(x['category'], ['Total', 'Ages 20-34', 'Ages 35-44', 'Ages 45-54', 'Ages 55-64', 'Less than High School', 'High School Graduate', 'Some College', 'College Graduate', 'Native-Born', 'Immigrant', 'White', 'Black', 'Latino', 'Asian', 'Male', 'Female', 'Veterans', 'Non-Veterans']))

    if df_out.shape[1] == 0:
        return df_v
    return df_out.merge(df_v, how='left', on=['name', 'fips', 'type', 'category', 'year'])


def raw_kese_formatter(state_file_path, us_file_path):
    """
    Formats the raw Kese data (i.e., what Rob gives us) for download.

    file_path_lst: lst
        List containing file paths of Excel file with the state-level and national-level KESE data.
    """
    indicator_dict = dict(
        zip(
            ['Rate of New Entrepreneurs', 'Opportunity Share of NE', 'Startup Job Creation', 'Startup Survival Rate',
             'KESE Index'],
            ['rne', 'ose', 'sjc', 'ssr', 'zindex']
        )
    )

    df_us, df_state = pd.DataFrame(), pd.DataFrame()
    for k, v in indicator_dict.items():
        df_state = _region_transform(pd.read_excel(state_file_path, sheet_name=k), v, df_state)
        df_us = _region_transform(pd.read_excel(us_file_path, sheet_name=k), v, df_us)

    return df_state.\
        append(df_us).\
        sort_values(['fips', 'category']).\
        reset_index(drop=True)


def _grouper(df_in):
    array = np.expand_dims(['Ages 0 to 1', 'Ages 2 to 3', 'Ages 4 to 5', 'Ages 6 to 10', 'Ages 11+'], 1)
    for col in ['age{age}_emp_per_total_emp', 'age{age}_pay_per_total_pay', 'stable_emp_per_total_emp_age{age}', 'net_change_jobs_per_cap_age{age}']:
        colx = map(lambda x: col.format(age=x), range(1, 6))

        vals = np.expand_dims(df_in[colx].transpose().iloc[:, 0].values, 1)
        array = np.c_[array, vals]
    array = np.c_[array, np.expand_dims(np.repeat(df_in['index_geo'].values, 5), 1)]
    return pd.DataFrame(array, columns=['category', 'contribution', 'compensation', 'constancy', 'creation', 'q2_index'])


def _fips_formatter(df, region):
    if region == 'us':
        return df.assign(fips='00')
    elif region == 'state':
        return df.assign(fips=lambda x: x['fips'].apply(lambda row: row if len(row) == 2 else '0' + row))
    else:
        return df.assign(fips=lambda x: x['fips'].apply(lambda row: '00' + row if len(row) == 3 else '0' + row if len(row) == 4 else row))


# todo: should these be in the public_data_helpers.py file or here?
def raw_jobs_formatter(file_path):
    """
    Formats the raw Jobs data (i.e., the output from /Users/thowe/Projects/jobs_indicators/indicators_create.py) for download.

    file_path: str
        String containing the directory of the files with the region specific raw Jobs indicators data.
    """

    if file_path[-1] != '/':
        file_path += '/'

    df = pd.concat(
        [
            pd.read_csv(file_path + 'indicators_{}.csv'.format(region)). \
                groupby(['name', 'fips', 'year']).apply(_grouper). \
                reset_index(drop=False). \
                astype({'fips': 'str'}).\
                pipe(_fips_formatter, region). \
                drop('level_3', 1)
            for region in ['county', 'msa', 'state', 'us']
        ]
    ).\
        reset_index(drop=True).\
        assign(type='Age of Business') \
        [['name', 'fips', 'type', 'category', 'year', 'contribution', 'compensation', 'constancy', 'creation', 'q2_index']]\

    return df.\
        append(df.query('category == "Ages 0 to 1"').assign(type='Total', category='Total')). \
        assign(category=lambda x: pd.Categorical(x['category'], ['Total', 'Ages 0 to 1', 'Ages 2 to 3', 'Ages 4 to 5', 'Ages 6 to 10', 'Ages 11+'])).\
        sort_values(['fips', 'year', 'category'])


def download_to_alley_formatter(df, covar_lst, outcome):
    """
    Formats downloadable data for Alley.

    covar_lst: lst
        List of covariates that are used to stratify the data.
    outcome: str
        The column name of the outcome whose values become the cells of the dataframe.
    """
    # data_in = self._obj
    # self._validate_panel(data_in, covar_lst)
    # todo: include some validator here

    return df[['fips', 'year'] + covar_lst + [outcome]].\
        pipe(pd.pivot_table, index=['fips'] + covar_lst, columns='year', values=outcome).\
        reset_index().\
        rename(columns={'fips': 'region'}).\
        replace('Total', '').\
        rename(columns={'type': 'demographic-type', 'category': 'demographic'})


if __name__ == '__main__':
    # aws_upload('/Users/thowe/Downloads/qwi_412506b63372496a91fad6c8029f9542.csv', 'emkf.data.research', 'new_employer_businesses/qwi.csv')
    # aws_download('/Users/thowe/Downloads/qwi.csv', 'emkf.data.research', 'new_employer_businesses/qwi.csv')

    # zip_to_dataframe('https://www2.census.gov/econ2016/SE/sector00/SE1600CSA01.zip?#')

    # import sys
    # df = raw_jobs_formatter('/Users/thowe/Projects/jobs_indicators/data/indicators')
    # for indicator in ['contribution', 'compensation', 'constancy', 'creation', 'q2_index']:
    #     df.\
    #         astype({'contribution': 'float'}).\
    #         pipe(download_to_alley_formatter, ['type', 'category'], 'contribution').\
    #         pipe(lambda x: print(x))
    #         # to_csv('/Users/thowe/Downloads/jobs_{}.csv')

    df = pd.read_csv('/Users/thowe/Downloads/raw_gsg_5.26.csv')
    weighted_crosstab(df, 'Q4', 'Q10', 'WEIGHT')