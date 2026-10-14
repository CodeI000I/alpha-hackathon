// Package files — объектное хранилище файлов компаний: RustFS в кластере, любой S3 снаружи.
// minio-go здесь просто S3-клиент, с сервером MinIO он не связан.
package files

import (
	"context"
	"io"

	"github.com/minio/minio-go/v7"
	"github.com/minio/minio-go/v7/pkg/credentials"

	"github.com/devowt/alpha-hackaton/backend/internal/config"
)

type Store struct {
	client *minio.Client
	bucket string
}

func New(ctx context.Context, c config.S3) (*Store, error) {
	client, err := minio.New(c.Endpoint, &minio.Options{
		Creds:  credentials.NewStaticV4(c.AccessKey, c.SecretKey, ""),
		Secure: c.UseSSL,
	})
	if err != nil {
		return nil, err
	}
	exists, err := client.BucketExists(ctx, c.Bucket)
	if err != nil {
		return nil, err
	}
	if !exists {
		if err := client.MakeBucket(ctx, c.Bucket, minio.MakeBucketOptions{}); err != nil {
			return nil, err
		}
	}
	return &Store{client: client, bucket: c.Bucket}, nil
}

func (s *Store) Put(ctx context.Context, key string, r io.Reader, size int64, contentType string) error {
	_, err := s.client.PutObject(ctx, s.bucket, key, r, size, minio.PutObjectOptions{ContentType: contentType})
	return err
}

func (s *Store) Get(ctx context.Context, key string) (io.ReadCloser, error) {
	return s.client.GetObject(ctx, s.bucket, key, minio.GetObjectOptions{})
}
